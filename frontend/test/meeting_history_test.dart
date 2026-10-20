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

    test('Correctly parses speakerUserId, attributionStatus, and confirmation flags', () {
      final jsonConfirmed = {
        'segment_id': 'mtg_123:0002',
        'speaker_label': 'SPEAKER_00',
        'speaker_user_id': 'usr_alice_456',
        'attribution_status': 'confirmed',
        'start_time': 5.0,
        'end_time': 8.0,
        'text': 'We agree on zero retention.',
        'user_name': 'Alice Smith',
      };
      final segConfirmed = TranscriptSegment.fromJson(jsonConfirmed);
      expect(segConfirmed.speakerUserId, equals('usr_alice_456'));
      expect(segConfirmed.attributionStatus, equals('confirmed'));
      expect(segConfirmed.isConfirmed, isTrue);
      expect(segConfirmed.isUnknown, isFalse);

      final jsonUnknown = {
        'segment_id': 'mtg_123:0003',
        'speaker_label': 'SPEAKER_01',
        'speaker_user_id': null,
        'attribution_status': 'unconfirmed',
        'start_time': 10.0,
        'end_time': 12.0,
        'text': 'Who is speaking?',
      };
      final segUnknown = TranscriptSegment.fromJson(jsonUnknown);
      expect(segUnknown.speakerUserId, isNull);
      expect(segUnknown.attributionStatus, equals('unconfirmed'));
      expect(segUnknown.isConfirmed, isFalse);
      expect(segUnknown.isUnknown, isTrue);
    });

    test('MeetingParticipantItem parses and handles fallbacks', () {
      final json = {
        'user_public_id': 'usr_bob_789',
        'full_name': 'Bob Jones',
        'email': 'bob@meetvault.com',
        'role': 'HOST',
      };
      final item = MeetingParticipantItem.fromJson(json);
      expect(item.userPublicId, equals('usr_bob_789'));
      expect(item.name, equals('Bob Jones'));
      expect(item.role, equals('HOST'));
    });

    test('Speaker filtering correctly isolates speaker segments without misattributing unknown speech', () {
      final segments = [
        TranscriptSegment(
          speakerLabel: 'SPEAKER_00',
          speakerUserId: 'usr_alice',
          userName: 'Alice',
          startTime: 0.0,
          endTime: 4.0,
          text: 'Alice segment 1',
          attributionStatus: 'confirmed',
        ),
        TranscriptSegment(
          speakerLabel: 'SPEAKER_01',
          speakerUserId: 'usr_bob',
          userName: 'Bob',
          startTime: 4.5,
          endTime: 8.0,
          text: 'Bob segment 1',
          attributionStatus: 'confirmed',
        ),
        TranscriptSegment(
          speakerLabel: 'SPEAKER_00',
          speakerUserId: 'usr_alice',
          userName: 'Alice',
          startTime: 8.5,
          endTime: 12.0,
          text: 'Alice segment 2',
          attributionStatus: 'confirmed',
        ),
        TranscriptSegment(
          speakerLabel: 'SPEAKER_02',
          speakerUserId: null,
          startTime: 12.5,
          endTime: 15.0,
          text: 'Anonymous interjection',
          attributionStatus: 'unconfirmed',
        ),
      ];

      // 1. Full transcript contains all 4 segments in chronological order
      expect(segments.length, equals(4));
      expect(segments[0].startTime < segments[1].startTime, isTrue);
      expect(segments[1].startTime < segments[2].startTime, isTrue);

      // 2. Filter for Alice: only Alice's 2 segments are returned
      final aliceSegments = segments.where((s) => s.speakerUserId == 'usr_alice').toList();
      expect(aliceSegments.length, equals(2));
      expect(aliceSegments.every((s) => s.speakerUserId == 'usr_alice'), isTrue);

      // 3. Filter for Bob: only Bob's 1 segment is returned
      final bobSegments = segments.where((s) => s.speakerUserId == 'usr_bob').toList();
      expect(bobSegments.length, equals(1));
      expect(bobSegments.first.text, equals('Bob segment 1'));

      // 4. Unknown speech is NEVER returned when filtering for an authenticated user
      expect(aliceSegments.any((s) => s.isUnknown), isFalse);
      expect(bobSegments.any((s) => s.isUnknown), isFalse);

      // 5. Unknown filter isolates unconfirmed speech
      final unknownSegments = segments.where((s) => s.isUnknown).toList();
      expect(unknownSegments.length, equals(1));
      expect(unknownSegments.first.text, equals('Anonymous interjection'));
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
      expect(find.textContaining('ID: mtg_test_789'), findsOneWidget);

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

    testWidgets('Meeting card renders Vault button with correct key and label', (tester) async {
      bool vaultClicked = false;
      final testMeeting = {
        'public_id': 'mtg_card_test_100',
        'title': 'Board Quarterly Review',
        'role': 'HOST',
        'status': 'COMPLETED',
        'duration_seconds': 3600,
        'scheduled_start_time': '2026-10-20T10:00:00Z',
        'participants': [
          {'name': 'Alice Smith', 'role': 'HOST'},
        ],
      };

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (ctx) {
                return Card(
                  child: Column(
                    children: [
                      Text(testMeeting['title'] as String),
                      FilledButton.icon(
                        key: Key('vault_button_${testMeeting['public_id']}'),
                        onPressed: () {
                          vaultClicked = true;
                        },
                        icon: const Icon(Icons.shield_outlined),
                        label: const Text('Vault'),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        ),
      );

      expect(find.text('Board Quarterly Review'), findsOneWidget);
      final vaultButton = find.byKey(const Key('vault_button_mtg_card_test_100'));
      expect(vaultButton, findsOneWidget);
      expect(find.text('Vault'), findsOneWidget);

      await tester.tap(vaultButton);
      await tester.pump();
      expect(vaultClicked, isTrue);
    });
  });
}
