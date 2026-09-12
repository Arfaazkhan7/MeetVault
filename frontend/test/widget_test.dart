import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:ai_meeting_system/core/providers/auth_provider.dart';
import 'package:ai_meeting_system/features/auth/login_screen.dart';

void main() {
  group('MeetVault Flutter Frontend Tests', () {
    test('AuthProvider initial state and displayName logic', () {
      final auth = AuthProvider();
      expect(auth.isAuthenticated, isFalse);
      expect(auth.isLoading, isFalse);
      expect(auth.errorMessage, isNull);
      expect(auth.displayName, equals('User'));
    });

    testWidgets('LoginScreen renders clean UI elements without layout overflow', (WidgetTester tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: ChangeNotifierProvider<AuthProvider>(
            create: (_) => AuthProvider(),
            child: const LoginScreen(),
          ),
        ),
      );

      // Verify header branding
      expect(find.text('Memora'), findsOneWidget);

      // Verify form fields
      expect(find.byType(TextFormField), findsNWidgets(2));
      expect(find.text('Email'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);

      // Verify sign in button
      expect(find.byType(ElevatedButton), findsOneWidget);
    });
  });
}
