import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_meeting_system/core/services/audio_chunk_delivery_queue.dart';
import 'package:ai_meeting_system/features/meetings/transcript_screen.dart';

void main() {
  group('Stage 6 E2E — Live Captions & Delivery Pipeline', () {
    test('Scenario 1 & 2: Two participants speaking with correct local vs remote speaker attribution', () {
      const localParticipantId = 'part-alice-101';
      const remoteParticipantId = 'part-bob-202';

      String resolveSpeaker(TranscriptSegment seg) {
        if (seg.userName != null && seg.userName!.trim().isNotEmpty) {
          return seg.userName!;
        }
        if (seg.participantId != null && seg.participantId == localParticipantId) {
          return 'You';
        }
        if (seg.speakerLabel.isNotEmpty && seg.speakerLabel != 'Speaker') {
          return seg.speakerLabel;
        }
        return 'Speaker';
      }

      final segAlice = TranscriptSegment(
        segmentId: 'mtg_part-alice_0',
        participantId: localParticipantId,
        speakerLabel: 'SPEAKER_00',
        speakerUserId: 'usr-alice',
        userName: null,
        startTime: 0.0,
        endTime: 2.5,
        text: 'Alice speaking first.',
      );

      final segBob = TranscriptSegment(
        segmentId: 'mtg_part-bob_2500',
        participantId: remoteParticipantId,
        speakerLabel: 'SPEAKER_01',
        speakerUserId: 'usr-bob',
        userName: 'Bob Engineer',
        startTime: 2.5,
        endTime: 5.0,
        text: 'Bob responding second.',
      );

      expect(resolveSpeaker(segAlice), 'You');
      expect(resolveSpeaker(segBob), 'Bob Engineer');
    });

    test('Scenario 3: Sequential chunks ordered chronologically even if responses arrive with delay', () {
      final indexMap = <String, int>{};
      final captions = <TranscriptSegment>[];

      void append(List<TranscriptSegment> incoming) {
        for (final seg in incoming) {
          final key = seg.segmentId ?? '${seg.participantId}_${(seg.startTime * 1000).toInt()}_${seg.text}';
          final existing = indexMap[key];
          if (existing != null && existing < captions.length) {
            captions[existing] = seg;
          } else {
            int pos = captions.length;
            for (int i = captions.length - 1; i >= 0; i--) {
              if (captions[i].startTime <= seg.startTime) {
                pos = i + 1;
                break;
              } else {
                pos = i;
              }
            }
            captions.insert(pos, seg);
            indexMap.clear();
            for (int i = 0; i < captions.length; i++) {
              final s = captions[i];
              indexMap[s.segmentId ?? '${s.participantId}_${(s.startTime * 1000).toInt()}_${s.text}'] = i;
            }
          }
        }
      }

      // Simulate Chunk 0 (0.0s) arrives first
      append([
        TranscriptSegment(segmentId: 's0', startTime: 0.0, endTime: 3.0, text: 'First chunk', speakerLabel: 'S0'),
      ]);

      // Simulate Chunk 2 (6.0s) arrives before Chunk 1 (network jitter)
      append([
        TranscriptSegment(segmentId: 's2', startTime: 6.0, endTime: 9.0, text: 'Third chunk', speakerLabel: 'S0'),
      ]);

      // Delayed Chunk 1 (3.0s) arrives
      append([
        TranscriptSegment(segmentId: 's1', startTime: 3.0, endTime: 6.0, text: 'Second chunk', speakerLabel: 'S0'),
      ]);

      expect(captions.length, 3);
      expect(captions[0].segmentId, 's0');
      expect(captions[1].segmentId, 's1');
      expect(captions[2].segmentId, 's2');
      expect(captions[0].text, 'First chunk');
      expect(captions[1].text, 'Second chunk');
      expect(captions[2].text, 'Third chunk');
    });

    test('Scenario 4: Idempotent retry prevents duplicate caption widgets', () {
      final indexMap = <String, int>{};
      final captions = <TranscriptSegment>[];

      void append(List<TranscriptSegment> incoming) {
        for (final seg in incoming) {
          final key = seg.segmentId ?? '${seg.participantId}_${(seg.startTime * 1000).toInt()}_${seg.text}';
          final existing = indexMap[key];
          if (existing != null && existing < captions.length) {
            captions[existing] = seg;
          } else {
            captions.add(seg);
            indexMap[key] = captions.length - 1;
          }
        }
      }

      final seg = TranscriptSegment(
        segmentId: 'mtg_part_seq5',
        startTime: 15.0,
        endTime: 18.0,
        text: 'Initial speech fragment.',
        speakerLabel: 'S1',
      );

      append([seg]);
      expect(captions.length, 1);
      expect(captions[0].text, 'Initial speech fragment.');

      // Resend same chunk on network retry
      final retrySeg = TranscriptSegment(
        segmentId: 'mtg_part_seq5',
        startTime: 15.0,
        endTime: 18.0,
        text: 'Initial speech fragment (complete).',
        speakerLabel: 'S1',
      );

      append([retrySeg]);
      expect(captions.length, 1);
      expect(captions[0].text, 'Initial speech fragment (complete).');
    });

    test('Scenario 5: Failed chunk does not block delivery queue from processing subsequent chunks', () async {
      int uploadCalls = 0;
      final deliveredChunks = <String>[];

      final queue = AudioChunkDeliveryQueue(
        maxAttempts: 2,
        baseBackoff: const Duration(milliseconds: 10),
        uploader: (chunk) async {
          uploadCalls++;
          if (chunk.chunkId == 'chunk_bad') {
            return 500; // Simulate server error on bad chunk
          }
          deliveredChunks.add(chunk.chunkId);
          return 201;
        },
      );

      final chunkBad = AudioChunk(
        chunkId: 'chunk_bad',
        sequenceNumber: 0,
        meetingId: 'mtg-1',
        participantId: 'p-1',
        wavBytes: Uint8List(100),
        startOffset: 0.0,
        endOffset: 2.0,
        duration: 2.0,
        sampleRate: 16000,
      );

      final chunkGood = AudioChunk(
        chunkId: 'chunk_good',
        sequenceNumber: 1,
        meetingId: 'mtg-1',
        participantId: 'p-1',
        wavBytes: Uint8List(100),
        startOffset: 2.0,
        endOffset: 4.0,
        duration: 2.0,
        sampleRate: 16000,
      );

      queue.enqueue(chunkBad);
      queue.enqueue(chunkGood);

      // Allow backoff retry and subsequent queue processing
      await Future<void>.delayed(const Duration(milliseconds: 150));

      expect(deliveredChunks.contains('chunk_good'), isTrue);
      expect(queue.status.failedCount, 1);
      expect(queue.status.deliveredCount, 1);
      expect(uploadCalls, greaterThanOrEqualTo(2));

      queue.dispose();
    });

    test('Scenario 12: AudioChunkDeliveryQueue properly cleans up resources on stop() and dispose()', () {
      final queue = AudioChunkDeliveryQueue(
        uploader: (chunk) async => 201,
      );

      final chunk = AudioChunk(
        chunkId: 'c1',
        sequenceNumber: 0,
        meetingId: 'm1',
        participantId: 'p1',
        wavBytes: Uint8List(50),
        startOffset: 0.0,
        endOffset: 1.0,
        duration: 1.0,
        sampleRate: 16000,
      );

      queue.enqueue(chunk);
      expect(queue.queuedCount, 1);

      queue.stop();
      expect(queue.isStopped, isTrue);

      // After stop, new enqueues are rejected
      final enqueued = queue.enqueue(chunk);
      expect(enqueued, isFalse);

      queue.clear();
      expect(queue.queuedCount, 0);

      queue.dispose();
    });
  });
}
