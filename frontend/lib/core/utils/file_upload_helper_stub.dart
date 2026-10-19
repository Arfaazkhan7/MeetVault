import 'dart:typed_data';

typedef FileUploadCallback = void Function(Uint8List bytes, String filename);

void pickAndUploadFile({
  required String accept,
  required FileUploadCallback onFilePicked,
}) {
  // Non-web platforms stub (used during flutter test execution)
}
