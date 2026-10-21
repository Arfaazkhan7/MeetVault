"""Bounded, text-only OOXML extraction for the Worker.

Read slide order and notes relationships, never render images or load Pillow
and lxml. No paths from the archive are written to the filesystem.
"""
import io
import posixpath
import zipfile
from xml.etree import ElementTree as ET

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def extract_slides(content: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 2048 or len(names) != len(set(names)):
            raise ValueError("Invalid or oversized presentation archive")
        xml_bytes = sum(e.file_size for e in entries if e.filename.endswith((".xml", ".rels")))
        if xml_bytes > 16 * 1024 * 1024:
            raise ValueError("Presentation XML exceeds the extraction limit")

        def xml(path):
            entry = archive.getinfo(path)
            if entry.file_size > 2 * 1024 * 1024:
                raise ValueError("Presentation XML part exceeds the extraction limit")
            data = archive.read(entry)
            declarations = data.replace(b"\x00", b"").upper()
            if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
                raise ValueError("XML declarations are not supported")
            return ET.fromstring(data)

        def relationships(part):
            folder, filename = posixpath.split(part)
            rel_path = posixpath.join(folder, "_rels", filename + ".rels")
            if rel_path not in names:
                return {}
            links = {}
            for rel in xml(rel_path):
                if rel.get("TargetMode", "Internal") != "Internal":
                    continue
                target = rel.get("Target", "")
                path = posixpath.normpath(posixpath.join(folder, target))
                if target.startswith("/"):
                    path = posixpath.normpath(target.lstrip("/"))
                if not path.startswith("ppt/") or "\\" in path:
                    raise ValueError("Invalid presentation relationship")
                links[rel.get("Id")] = (rel.get("Type", ""), path)
            return links

        def paragraphs(root):
            result = []
            for paragraph in root.iter(f"{{{A}}}p"):
                pieces = []
                for element in paragraph.iter():
                    if element.tag == f"{{{A}}}t":
                        pieces.append(element.text or "")
                    elif element.tag == f"{{{A}}}br":
                        pieces.append("\n")
                text = "".join(pieces).strip()
                if text:
                    result.append(text)
            return result

        presentation = "ppt/presentation.xml"
        slide_ids = xml(presentation).findall(f"{{{P}}}sldIdLst/{{{P}}}sldId")
        if len(slide_ids) > 200:
            raise ValueError("Presentations are limited to 200 slides")
        links = relationships(presentation)
        slides = []
        for number, slide_id in enumerate(slide_ids, 1):
            kind, path = links[slide_id.get(f"{{{R}}}id")]
            if not kind.endswith("/slide"):
                raise ValueError("Invalid slide relationship")
            text = paragraphs(xml(path))
            for kind, notes_path in relationships(path).values():
                if kind.endswith("/notesSlide"):
                    notes = []
                    for shape in xml(notes_path).iter(f"{{{P}}}sp"):
                        placeholder = shape.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
                        if placeholder is not None and placeholder.get("type") == "body":
                            notes.extend(paragraphs(shape))
                    if notes:
                        text.append("Notes: " + "\n".join(notes))
            slides.append({"page_number": number, "text_content": "\n".join(text)})
        return slides
