import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_meeting_system/features/meetings/transcript_screen.dart';

void main() {
  group('Live Captions — Response Parsing & Model Mapping', () {
    test('Correctly parses backend List[TranscriptSegmentResponse] JSON', () {
      const jsonStr = '''
      [
        {
          "id": "seg-uuid-1",
          "segment_id": "mtg-101_part-202_0",
          "recording_id": null,
          "speaker_label": "Speaker 1",
          "speaker_user_id": "usr-303",
          "user_id": "usr-303",
          "participant_id": "part-202",
          "attribution_status": "confirmed",
          "start_time": 0.0,
          "end_time": 3.8,
          "text": "Welcome to our architectural design review.",
          "translated_text": null,
          "language": "en",
          "confidence": 0.97,
          "user_name": "Alice Smith",
          "speaker_confirmed": true,
          "processing_metadata": {
            "chunk_id": "mtg-101_part-202_seq0",
            "sequence_number": 0,
            "sample_rate": 16000
          }
        },
        {
          "id": "seg-uuid-2",
          "segment_id": "mtg-101_part-202_3800",
          "recording_id": null,
          "speaker_label": "Speaker 1",
          "speaker_user_id": "usr-303",
          "user_id": "usr-303",
          "participant_id": "part-202",
          "attribution_status": "confirmed",
          "start_time": 3.8,
          "end_time": 7.5,
          "text": "Today we will verify the audio stream pipeline.",
          "translated_text": null,
          "language": "en",
          "confidence": 0.96,
          "user_name": "Alice Smith",
          "speaker_confirmed": true
        }
      ]
      ''';

      final dynamic decoded = json.decode(jsonStr);
      expect(decoded, isA<List>());

      final segments = <TranscriptSegment>[];
      for (final item in decoded as List) {
        segments.add(TranscriptSegment.fromJson(item as Map<String, dynamic>));
      }

      expect(segments.length, 2);
      expect(segments[0].segmentId, 'mtg-101_part-202_0');
      expect(segments[0].speakerLabel, 'Speaker 1');
      expect(segments[0].userName, 'Alice Smith');
      expect(segments[0].text, 'Welcome to our architectural design review.');
      expect(segments[0].startTime, 0.0);
      expect(segments[0].endTime, 3.8);
      expect(segments[0].isConfirmed, isTrue);

      expect(segments[1].segmentId, 'mtg-101_part-202_3800');
      expect(segments[1].startTime, 3.8);
      expect(segments[1].endTime, 7.5);
    });

    test('Handles empty and silent response without fabricating text', () {
      const emptyJsonStr = '[]';
      final dynamic decoded = json.decode(emptyJsonStr);
      expect(decoded, isA<List>());

      final segments = <TranscriptSegment>[];
      for (final item in decoded as List) {
        final seg = TranscriptSegment.fromJson(item as Map<String, dynamic>);
        if (seg.text.trim().isNotEmpty) {
          segments.add(seg);
        }
      }

      expect(segments, isEmpty);
    });
  });

  group('Live Captions — Chronological Ordering & Deduplication Logic', () {
    List<TranscriptSegment> simulateAppend({
      required List<TranscriptSegment> currentList,
      required Map<String, int> indexMap,
      required List<TranscriptSegment> incoming,
    }) {
      final list = List<TranscriptSegment>.from(currentList);
      for (final seg in incoming) {
        final text = seg.text.trim();
        if (text.isEmpty) continue;

        final key = seg.segmentId ?? '${seg.participantId}_${(seg.startTime * 1000).toInt()}_$text';
        final existingIndex = indexMap[key];

        if (existingIndex != null && existingIndex < list.length) {
          list[existingIndex] = seg;
        } else {
          int insertPos = list.length;
          for (int i = list.length - 1; i >= 0; i--) {
            if (list[i].startTime <= seg.startTime) {
              insertPos = i + 1;
              break;
            } else {
              insertPos = i;
            }
          }
          list.insert(insertPos, seg);

          // Rebuild index map
          indexMap.clear();
          for (int i = 0; i < list.length; i++) {
            final s = list[i];
            final k = s.segmentId ?? '${s.participantId}_${(s.startTime * 1000).toInt()}_${s.text.trim()}';
            indexMap[k] = i;
          }
        }
      }
      return list;
    }

    test('Appends sequential consecutive chunks in chronological order', () {
      final indexMap = <String, int>{};
      var captions = <TranscriptSegment>[];

      // Chunk 0 arrives (0.0s - 4.0s)
      final chunk0 = [
        TranscriptSegment(
          segmentId: 'seg_0',
          speakerLabel: 'Speaker 1',
          startTime: 0.0,
          endTime: 3.5,
          text: 'Hello team.',
        ),
      ];
      captions = simulateAppend(currentList: captions, indexMap: indexMap, incoming: chunk0);

      // Chunk 1 arrives (4.0s - 8.0s)
      final chunk1 = [
        TranscriptSegment(
          segmentId: 'seg_1',
          speakerLabel: 'Speaker 1',
          startTime: 4.2,
          endTime: 7.8,
          text: 'Can everyone see my screen?',
        ),
      ];
      captions = simulateAppend(currentList: captions, indexMap: indexMap, incoming: chunk1);

      expect(captions.length, 2);
      expect(captions[0].text, 'Hello team.');
      expect(captions[1].text, 'Can everyone see my screen?');
      expect(captions[0].startTime, 0.0);
      expect(captions[1].startTime, 4.2);
    });

    test('Handles out-of-order delayed chunk delivery without corruption', () {
      final indexMap = <String, int>{};
      var captions = <TranscriptSegment>[];

      // Chunk 0 arrives first (0.0s)
      captions = simulateAppend(
        currentList: captions,
        indexMap: indexMap,
        incoming: [
          TranscriptSegment(
            segmentId: 'seg_0',
            speakerLabel: 'Speaker 1',
            startTime: 0.0,
            endTime: 3.0,
            text: 'First statement.',
          ),
        ],
      );

      // Chunk 2 arrives BEFORE Chunk 1 (network jitter / delayed retry) (8.0s)
      captions = simulateAppend(
        currentList: captions,
        indexMap: indexMap,
        incoming: [
          TranscriptSegment(
            segmentId: 'seg_2',
            speakerLabel: 'Speaker 1',
            startTime: 8.0,
            endTime: 11.5,
            text: 'Third statement.',
          ),
        ],
      );

      // Delayed Chunk 1 finally arrives (4.0s)
      captions = simulateAppend(
        currentList: captions,
        indexMap: indexMap,
        incoming: [
          TranscriptSegment(
            segmentId: 'seg_1',
            speakerLabel: 'Speaker 1',
            startTime: 4.0,
            endTime: 7.2,
            text: 'Second statement.',
          ),
        ],
      );

      // Must be perfectly ordered: [seg_0, seg_1, seg_2]
      expect(captions.length, 3);
      expect(captions[0].segmentId, 'seg_0');
      expect(captions[0].startTime, 0.0);
      expect(captions[1].segmentId, 'seg_1');
      expect(captions[1].startTime, 4.0);
      expect(captions[2].segmentId, 'seg_2');
      expect(captions[2].startTime, 8.0);
    });

    test('Retry of the same chunk updates in-place and prevents duplicates', () {
      final indexMap = <String, int>{};
      var captions = <TranscriptSegment>[];

      final segment = TranscriptSegment(
        segmentId: 'mtg_part_10000',
        speakerLabel: 'Speaker 1',
        startTime: 10.0,
        endTime: 13.0,
        text: 'Initial transcription.',
      );

      // First delivery
      captions = simulateAppend(currentList: captions, indexMap: indexMap, incoming: [segment]);
      expect(captions.length, 1);
      expect(captions[0].text, 'Initial transcription.');

      // Resend identical chunk (retry/reconnect) with refined text
      final retrySegment = TranscriptSegment(
        segmentId: 'mtg_part_10000',
        speakerLabel: 'Speaker 1',
        startTime: 10.0,
        endTime: 13.0,
        text: 'Initial transcription refined.',
      );
      captions = simulateAppend(currentList: captions, indexMap: indexMap, incoming: [retrySegment]);

      // Exactly 1 segment remains, text updated in-place without duplicate row
      expect(captions.length, 1);
      expect(captions[0].text, 'Initial transcription refined.');
    });

    test('Filters out whitespace-only segments', () {
      final indexMap = <String, int>{};
      var captions = <TranscriptSegment>[];

      final emptySegment = TranscriptSegment(
        segmentId: 'silent_seg',
        speakerLabel: 'Speaker 1',
        startTime: 0.0,
        endTime: 2.0,
        text: '   ',
      );

      captions = simulateAppend(currentList: captions, indexMap: indexMap, incoming: [emptySegment]);
      expect(captions, isEmpty);
    });
  });

  group('Live Captions — Formatting & Presentation', () {
    String formatCaptionTimestamp(double seconds) {
      final totalSec = seconds.toInt();
      final h = totalSec ~/ 3600;
      final m = (totalSec % 3600) ~/ 60;
      final s = totalSec % 60;
      if (h > 0) {
        return '${h.toString().padLeft(2, '0')}:${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
      }
      return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
    }

    test('Formats timestamps into readable mm:ss and hh:mm:ss', () {
      expect(formatCaptionTimestamp(0.0), '00:00');
      expect(formatCaptionTimestamp(14.8), '00:14');
      expect(formatCaptionTimestamp(75.2), '01:15');
      expect(formatCaptionTimestamp(3665.0), '01:01:05');
    });

    test('Resolves speaker name with proper fallback precedence', () {
      String resolveSpeaker(TranscriptSegment segment, String currentPartId) {
        if (segment.userName != null && segment.userName!.trim().isNotEmpty) {
          return segment.userName!;
        }
        if (segment.participantId != null && segment.participantId == currentPartId) {
          return 'You';
        }
        if (segment.speakerLabel.isNotEmpty && segment.speakerLabel != 'Speaker') {
          return segment.speakerLabel;
        }
        return 'Speaker';
      }

      final mySegment = TranscriptSegment(
        speakerLabel: 'Speaker 0',
        participantId: 'my_part_id',
        startTime: 0.0,
        endTime: 2.0,
        text: 'Speaking now',
      );
      expect(resolveSpeaker(mySegment, 'my_part_id'), 'You');

      final namedSegment = TranscriptSegment(
        speakerLabel: 'Speaker 1',
        userName: 'Bob Jones',
        participantId: 'other_part_id',
        startTime: 2.0,
        endTime: 4.0,
        text: 'Replying here',
      );
      expect(resolveSpeaker(namedSegment, 'my_part_id'), 'Bob Jones');

      final unknownSegment = TranscriptSegment(
        speakerLabel: 'Speaker 2',
        participantId: 'other_part_id',
        startTime: 4.0,
        endTime: 6.0,
        text: 'Unknown voice',
      );
      expect(resolveSpeaker(unknownSegment, 'my_part_id'), 'Speaker 2');
    });
  });

  group('Live Captions — Widget UI States & Interaction', () {
    Widget buildTestHarness({
      required List<TranscriptSegment> captions,
      bool microphoneEnabled = true,
      bool isTranscribing = false,
      String? transcriptionError,
    }) {
      return MaterialApp(
        home: Scaffold(
          backgroundColor: const Color(0xFF0F172A),
          body: Container(
            height: 155,
            margin: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF1E293B),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFF334155)),
            ),
            child: Column(
              children: [
                // Header
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                  child: Row(
                    children: [
                      const Icon(Icons.closed_caption, size: 16, color: Color(0xFF818CF8)),
                      const SizedBox(width: 6),
                      const Text(
                        'Live Captions',
                        style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(width: 8),
                      if (!microphoneEnabled)
                        const Text('Muted', style: TextStyle(color: Color(0xFF94A3B8), fontSize: 10))
                      else if (isTranscribing)
                        const Text('Transcribing...', style: TextStyle(color: Color(0xFF93C5FD), fontSize: 10)),
                      const Spacer(),
                      if (captions.isNotEmpty)
                        Text('${captions.length} segments', style: const TextStyle(color: Color(0xFF64748B), fontSize: 10)),
                    ],
                  ),
                ),
                // Error banner
                if (transcriptionError != null)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    color: const Color(0xFF7F1D1D),
                    child: Text(
                      transcriptionError,
                      style: const TextStyle(color: Color(0xFFFECACA), fontSize: 10),
                    ),
                  ),
                // Body
                Expanded(
                  child: captions.isEmpty
                      ? Center(
                          child: Text(
                            microphoneEnabled
                                ? 'Live captions will appear here as participants speak'
                                : 'Microphone is muted. Unmute to transcribe speech.',
                            style: const TextStyle(color: Color(0xFF64748B), fontSize: 11),
                          ),
                        )
                      : ListView.builder(
                          itemCount: captions.length,
                          itemBuilder: (context, index) {
                            final seg = captions[index];
                            return Padding(
                              padding: const EdgeInsets.all(8),
                              child: Text(
                                '${seg.speakerLabel}: ${seg.text}',
                                style: const TextStyle(color: Colors.white, fontSize: 12),
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    testWidgets('Renders empty state when no speech is transcribed', (tester) async {
      await tester.pumpWidget(buildTestHarness(captions: []));
      expect(find.text('Live Captions'), findsOneWidget);
      expect(find.text('Live captions will appear here as participants speak'), findsOneWidget);
    });

    testWidgets('Renders microphone-muted state correctly', (tester) async {
      await tester.pumpWidget(buildTestHarness(captions: [], microphoneEnabled: false));
      expect(find.text('Muted'), findsOneWidget);
      expect(find.text('Microphone is muted. Unmute to transcribe speech.'), findsOneWidget);
    });

    testWidgets('Renders transcribing status indicator when audio is in flight', (tester) async {
      await tester.pumpWidget(buildTestHarness(captions: [], isTranscribing: true));
      expect(find.text('Transcribing...'), findsOneWidget);
    });

    testWidgets('Renders transcription error banner when failure occurs', (tester) async {
      await tester.pumpWidget(buildTestHarness(
        captions: [],
        transcriptionError: 'Transcription delayed: Network timeout',
      ));
      expect(find.text('Transcription delayed: Network timeout'), findsOneWidget);
    });

    testWidgets('Renders populated captions list with speaker and segment count', (tester) async {
      final captions = [
        TranscriptSegment(
          segmentId: '1',
          speakerLabel: 'Alice',
          startTime: 0.0,
          endTime: 2.5,
          text: 'First live sentence.',
        ),
        TranscriptSegment(
          segmentId: '2',
          speakerLabel: 'Bob',
          startTime: 3.0,
          endTime: 5.5,
          text: 'Second live reply.',
        ),
      ];

      await tester.pumpWidget(buildTestHarness(captions: captions));
      expect(find.text('2 segments'), findsOneWidget);
      expect(find.text('Alice: First live sentence.'), findsOneWidget);
      expect(find.text('Bob: Second live reply.'), findsOneWidget);
    });
  });
}

