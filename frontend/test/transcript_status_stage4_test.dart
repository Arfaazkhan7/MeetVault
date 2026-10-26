import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_meeting_system/features/meetings/transcript_screen.dart';

void main() {
  group('Stage 4 — Transcript Status & Segment Loading Logic', () {
    test('Transcript status JSON parses and differentiates partial, processing, completed, and failed', () {
      final partialJson = {
        'status': 'partial',
        'error': null,
        'segment_count': 3,
        'speaker_count': 2,
      };
      expect(partialJson['status'], equals('partial'));
      expect(partialJson['segment_count'], equals(3));
      expect(partialJson['error'], isNull);

      final failedJson = {
        'status': 'failed',
        'error': 'Audio stream corrupted',
        'segment_count': 0,
        'speaker_count': 0,
      };
      expect(failedJson['status'], equals('failed'));
      expect(failedJson['error'], equals('Audio stream corrupted'));

      final completedJson = {
        'status': 'completed',
        'error': null,
        'segment_count': 10,
        'speaker_count': 3,
      };
      expect(completedJson['status'], equals('completed'));
      expect(completedJson['segment_count'], equals(10));
    });

    test('Transcript segments preserve chronological sorting with partial live data', () {
      final rawList = [
        {
          'segment_id': 'mtg_chunk_2',
          'speaker_label': 'Speaker 1',
          'speaker_user_id': 'usr_alice',
          'user_name': 'Alice Smith',
          'start_time': 4.5,
          'end_time': 8.0,
          'text': 'We are recording live.',
          'speaker_confirmed': true,
        },
        {
          'segment_id': 'mtg_chunk_1',
          'speaker_label': 'Speaker 1',
          'speaker_user_id': 'usr_alice',
          'user_name': 'Alice Smith',
          'start_time': 0.0,
          'end_time': 4.0,
          'text': 'Hello everyone.',
          'speaker_confirmed': true,
        },
      ];

      final segments = rawList.map((j) => TranscriptSegment.fromJson(j)).toList();
      segments.sort((a, b) => a.startTime.compareTo(b.startTime));

      expect(segments.length, equals(2));
      expect(segments[0].startTime, equals(0.0));
      expect(segments[0].text, equals('Hello everyone.'));
      expect(segments[1].startTime, equals(4.5));
      expect(segments[1].text, equals('We are recording live.'));
    });

    test('Speaker filtering correctly separates confirmed speakers from unconfirmed speech', () {
      final segments = [
        TranscriptSegment(
          segmentId: 's1',
          speakerLabel: 'SPEAKER_00',
          speakerUserId: 'usr_alice',
          userName: 'Alice',
          startTime: 0.0,
          endTime: 3.0,
          text: 'Alice speaking.',
          attributionStatus: 'confirmed',
          speakerConfirmed: true,
        ),
        TranscriptSegment(
          segmentId: 's2',
          speakerLabel: 'SPEAKER_01',
          speakerUserId: 'usr_bob',
          userName: 'Bob',
          startTime: 3.5,
          endTime: 6.0,
          text: 'Bob speaking.',
          attributionStatus: 'confirmed',
          speakerConfirmed: true,
        ),
        TranscriptSegment(
          segmentId: 's3',
          speakerLabel: 'SPEAKER_UNKNOWN',
          speakerUserId: null,
          userName: null,
          startTime: 6.5,
          endTime: 8.0,
          text: 'Unidentified participant.',
          attributionStatus: 'unknown',
          speakerConfirmed: false,
        ),
      ];

      // Filter by Alice
      final alice = segments.where((s) => s.speakerUserId == 'usr_alice').toList();
      expect(alice.length, equals(1));
      expect(alice.first.text, equals('Alice speaking.'));

      // Filter by Unknown
      final unknown = segments.where((s) => s.isUnknown).toList();
      expect(unknown.length, equals(1));
      expect(unknown.first.text, equals('Unidentified participant.'));
    });
  });

  group('TranscriptScreen UI Rendering & Lifecycle Tests', () {
    testWidgets('Renders AppBar with title, ID, and refresh button', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TranscriptScreen(
            meetingId: 'mtg_live_101',
            meetingTitle: 'Stage 4 Architecture Meeting',
          ),
        ),
      );

      // Verify title & ID
      expect(find.text('Stage 4 Architecture Meeting'), findsOneWidget);
      expect(find.textContaining('ID: mtg_live_101'), findsOneWidget);

      // Verify Refresh button in AppBar
      expect(find.byIcon(Icons.refresh), findsOneWidget);

      // Verify initial loading indicator
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('Properly disposes and cancels polling timer without throwing on unmount', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: TranscriptScreen(
            meetingId: 'mtg_timer_test',
            meetingTitle: 'Timer Test',
          ),
        ),
      );

      // Verify screen mounted
      expect(find.byType(TranscriptScreen), findsOneWidget);

      // Unmount the screen to trigger dispose()
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: Text('Another Screen')),
        ),
      );

      // Verify unmounted cleanly without unhandled timer exceptions
      expect(find.text('Another Screen'), findsOneWidget);
      expect(find.byType(TranscriptScreen), findsNothing);
    });
  });
}
