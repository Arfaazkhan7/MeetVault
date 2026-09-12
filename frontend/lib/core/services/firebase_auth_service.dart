import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';

class FirebaseAuthService {
  Future<String> signInWithGoogleAndGetIdToken() async {
    if (Firebase.apps.isEmpty) {
      throw FirebaseAuthException(
        code: 'firebase-not-configured',
        message: 'Google sign-in is not configured yet. Add FIREBASE_API_KEY during the Flutter build.',
      );
    }

    final provider = GoogleAuthProvider()
      ..addScope('email')
      ..addScope('profile');

    final credential = await FirebaseAuth.instance.signInWithPopup(provider);
    final token = await credential.user?.getIdToken();
    if (token == null || token.isEmpty) {
      throw FirebaseAuthException(
        code: 'missing-id-token',
        message: 'Google sign-in completed, but no Firebase token was returned.',
      );
    }
    return token;
  }

  Future<void> signOut() async {
    if (Firebase.apps.isNotEmpty) {
      await FirebaseAuth.instance.signOut();
    }
  }
}
