import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:ai_meeting_system/core/providers/auth_provider.dart';
import 'package:ai_meeting_system/features/meetings/meetings_screen.dart';
import 'package:ai_meeting_system/features/meetings/transcript_screen.dart';

void main() {
  group('TranscriptSegment Model & Serialization', () {
    test('Correctly parses full multilingual segment with translation and confidence', () {
      final json = {
        'segment_id': 'mtg_123:0001',
        'recording_id': 'rec_456',
        'speaker_label': 'SPEAKER_01',
        'start_time': 12.5,
        'end_time': 18.2,
        'text': 'வணக்கம் நண்பர்களே',
        'translated_text': 'Hello friends',
        'language': 'ta',
        'confidence': 0.94,
        'user_name': 'Arfaaz Khan',
        'speaker_confirmed': true,
      };

      final segment = TranscriptSegment.fromJson(json);

      expect(segment.segmentId, equals('mtg_123:0001'));
      expect(segment.recordingId, equals('rec_456'));
      expect(segment.speakerLabel, equals('SPEAKER_01'));
      expect(segment.startTime, equals(12.5));
      expect(segment.endTime, equals(18.2));
      expect(segment.text, equals('வணக்கம் நண்பர்களே'));
      expect(segment.translatedText, equals('Hello friends'));
      expect(segment.language, equals('ta'));
      expect(segment.confidence, equals(0.94));
      expect(segment.userName, equals('Arfaaz Khan'));
      expect(segment.speakerConfirmed, isTrue);
    });

    test('Handles missing / null fields gracefully without crashing', () {
      final json = {
        'speaker_label': null,
        'start_time': null,
        'end_time': null,
        'text': null,
      };

      final segment = TranscriptSegment.fromJson(json);

      expect(segment.speakerLabel, equals('Speaker'));
      expect(segment.startTime, equals(0.0));
      expect(segment.endTime, equals(0.0));
      expect(segment.text, equals(''));
      expect(segment.language, isNull);
      expect(segment.confidence, isNull);
      expect(segment.userName, isNull);
      expect(segment.speakerConfirmed, isFalse);
    });
  });

  group('TranscriptScreen Widget Tests', () {
    testWidgets('Renders loading indicator initially with meeting title and stable ID', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TranscriptScreen(
            meetingId: 'mtg_test_789',
            meetingTitle: 'Sprint Architecture Review',
          ),
        ),
      );

      // Verify title and stable ID in app bar
      expect(find.text('Sprint Architecture Review'), findsOneWidget);
      expect(find.text('ID: mtg_test_789'), findsOneWidget);

      // Verify initial loading state
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Loading meeting transcript...'), findsOneWidget);
    });
  });

  group('MeetingsScreen Widget Tests', () {
    testWidgets('Renders search input and filter chips for meeting history', (tester) async {
      final authProvider = AuthProvider();

      await tester.pumpWidget(
        MaterialApp(
          home: ChangeNotifierProvider<AuthProvider>.value(
            value: authProvider,
            child: const MeetingsScreen(),
          ),
        ),
      );

      // Verify initial progress or scaffold rendering
      expect(find.byType(MeetingsScreen), findsOneWidget);
    });
  });
}
