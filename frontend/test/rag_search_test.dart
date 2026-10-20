import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:ai_meeting_system/core/providers/auth_provider.dart';
import 'package:ai_meeting_system/features/search/search_screen.dart';
import 'package:ai_meeting_system/features/memory/ask_memory_screen.dart';

void main() {
  group('SearchScreen & AskMemoryScreen Widget Tests', () {
    testWidgets('SearchScreen renders semantic search and ask memory tabs cleanly', (tester) async {
      final authProvider = AuthProvider();

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<AuthProvider>.value(value: authProvider),
          ],
          child: const MaterialApp(
            home: SearchScreen(),
          ),
        ),
      );

      // Verify tabs are present
      expect(find.text('Semantic Search'), findsOneWidget);
      expect(find.text('Ask Memory'), findsOneWidget);

      // Verify search input field exists
      expect(find.byType(TextField), findsWidgets);
      expect(find.text('Search'), findsOneWidget);
      expect(find.text('Index Memory'), findsOneWidget);
    });

    testWidgets('AskMemoryScreen renders question input and sample chips', (tester) async {
      final authProvider = AuthProvider();

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<AuthProvider>.value(value: authProvider),
          ],
          child: const MaterialApp(
            home: AskMemoryScreen(),
          ),
        ),
      );

      // Verify title and ask button
      expect(find.text('Ask Meeting Memory'), findsOneWidget);
      expect(find.text('Ask Memory'), findsOneWidget);

      // Verify sample question chip exists
      expect(find.text('What did we discuss about authentication?'), findsOneWidget);
    });
  });
}
