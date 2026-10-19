// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:typed_data';

typedef FileUploadCallback = void Function(Uint8List bytes, String filename);

void pickAndUploadFile({
  required String accept,
  required FileUploadCallback onFilePicked,
}) {
  final uploadInput = html.FileUploadInputElement();
  uploadInput.accept = accept;
  uploadInput.click();

  uploadInput.onChange.listen((e) {
    final files = uploadInput.files;
    if (files == null || files.isEmpty) return;
    final file = files[0];
    final reader = html.FileReader();
    reader.readAsArrayBuffer(file);
    reader.onLoadEnd.listen((e) {
      final bytes = reader.result as Uint8List;
      onFilePicked(bytes, file.name);
    });
  });
}
