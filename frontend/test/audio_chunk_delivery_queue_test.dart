import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_meeting_system/core/services/audio_chunk_delivery_queue.dart';

void main() {
  group('AudioChunkDeliveryQueue — Delivery, Retry and Concurrency', () {
    AudioChunk createSampleChunk({
      int seq = 0,
      int byteCount = 1000,
      String meetingId = 'mtg-test',
      String participantId = 'part-test',
    }) {
      return AudioChunk(
        chunkId: '${meetingId}_${participantId}_seq$seq',
        sequenceNumber: seq,
        meetingId: meetingId,
        participantId: participantId,
        wavBytes: Uint8List(byteCount),
        startOffset: seq * 4.0,
        endOffset: (seq + 1) * 4.0,
        duration: 4.0,
        sampleRate: 16000,
      );
    }

    test('Successfully delivers chunk and triggers acknowledgment callback', () async {
      final deliveredChunks = <AudioChunk>[];
      final queue = AudioChunkDeliveryQueue(
        uploader: (chunk) async {
          return 201; // Success
        },
        onChunkDelivered: (chunk) {
          deliveredChunks.add(chunk);
        },
      );

      final chunk0 = createSampleChunk(seq: 0);
      final enqueued = queue.enqueue(chunk0);
      expect(enqueued, isTrue);

      // Allow async processing to complete
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(deliveredChunks.length, 1);
      expect(deliveredChunks.first.chunkId, chunk0.chunkId);
      expect(queue.queuedCount, 0);
      expect(queue.status.deliveredCount, 1);
      expect(queue.status.failedCount, 0);
      expect(queue.status.droppedCount, 0);

      queue.dispose();
    });

    test('Sequential execution: strictly one in-flight chunk at a time, eliminating overlapping requests', () async {
      int concurrentInFlight = 0;
      int maxConcurrentObserved = 0;
      final deliveryOrder = <int>[];

      final queue = AudioChunkDeliveryQueue(
        uploader: (chunk) async {
          concurrentInFlight++;
          if (concurrentInFlight > maxConcurrentObserved) {
            maxConcurrentObserved = concurrentInFlight;
          }
          await Future<void>.delayed(const Duration(milliseconds: 30));
          deliveryOrder.add(chunk.sequenceNumber);
          concurrentInFlight--;
          return 201;
        },
      );

      // Enqueue 3 chunks rapidly
      queue.enqueue(createSampleChunk(seq: 0));
      queue.enqueue(createSampleChunk(seq: 1));
      queue.enqueue(createSampleChunk(seq: 2));

      // Wait for all to complete
      await Future<void>.delayed(const Duration(milliseconds: 200));

      expect(maxConcurrentObserved, 1, reason: 'Must never process overlapping chunks concurrently');
      expect(deliveryOrder, [0, 1, 2], reason: 'Must preserve strict FIFO chronological delivery');
      expect(queue.queuedCount, 0);

      queue.dispose();
    });

    test('Transient failure (500 error) retries without permanently discarding audio', () async {
      int attempts = 0;
      final delivered = <AudioChunk>[];

      final queue = AudioChunkDeliveryQueue(
        baseBackoff: const Duration(milliseconds: 50),
        maxBackoff: const Duration(milliseconds: 200),
        uploader: (chunk) async {
          attempts++;
          if (attempts == 1) {
            return 500; // First attempt fails with transient server error
          }
          return 201; // Subsequent attempt succeeds
        },
        onChunkDelivered: (chunk) {
          delivered.add(chunk);
        },
      );

      final chunk = createSampleChunk(seq: 0);
      queue.enqueue(chunk);

      // Initial dispatch fails
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(attempts, 1);
      expect(queue.queuedCount, 1, reason: 'Chunk must NOT be discarded on transient failure');
      expect(chunk.attempts, 1);
      expect(chunk.nextRetryAt, isNotNull);

      // Wait for exponential backoff retry to trigger
      await Future<void>.delayed(const Duration(milliseconds: 150));

      expect(attempts, 2);
      expect(delivered.length, 1);
      expect(queue.queuedCount, 0, reason: 'Acknowledged chunk is removed after retry succeeds');

      queue.dispose();
    });

    test('Network exception (SocketException/timeout) is treated as retryable failure', () async {
      int attempts = 0;
      final queue = AudioChunkDeliveryQueue(
        baseBackoff: const Duration(milliseconds: 50),
        uploader: (chunk) async {
          attempts++;
          if (attempts == 1) {
            throw TimeoutException('Network request timed out');
          }
          return 201;
        },
      );

      final chunk = createSampleChunk(seq: 0);
      queue.enqueue(chunk);

      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(attempts, 1);
      expect(queue.queuedCount, 1);
      expect(chunk.lastError, contains('Network request timed out'));

      await Future<void>.delayed(const Duration(milliseconds: 150));
      expect(attempts, 2);
      expect(queue.queuedCount, 0);

      queue.dispose();
    });

    test('Permanent failures (400, 401, 403, 404) fail fast without retrying', () async {
      for (final code in [400, 401, 403, 404]) {
        int attempts = 0;
        final failedChunks = <AudioChunk>[];

        final queue = AudioChunkDeliveryQueue(
          uploader: (chunk) async {
            attempts++;
            return code;
          },
          onPermanentFailure: (chunk, error) {
            failedChunks.add(chunk);
          },
        );

        queue.enqueue(createSampleChunk(seq: code));
        await Future<void>.delayed(const Duration(milliseconds: 30));

        expect(attempts, 1, reason: 'HTTP $code must not be retried');
        expect(failedChunks.length, 1);
        expect(queue.queuedCount, 0, reason: 'Permanently failed chunk must be removed to avoid clogging');
        expect(queue.status.failedCount, 1);

        queue.dispose();
      }
    });

    test('Max retry attempts bounds retries and prevents infinite loops', () async {
      int attempts = 0;
      AudioChunk? permanentFailChunk;

      final queue = AudioChunkDeliveryQueue(
        maxAttempts: 3,
        baseBackoff: const Duration(milliseconds: 20),
        maxBackoff: const Duration(milliseconds: 50),
        uploader: (chunk) async {
          attempts++;
          return 503; // Always returns Service Unavailable
        },
        onPermanentFailure: (chunk, error) {
          permanentFailChunk = chunk;
        },
      );

      queue.enqueue(createSampleChunk(seq: 0));

      // Wait long enough for 3 attempts + backoffs
      await Future<void>.delayed(const Duration(milliseconds: 300));

      expect(attempts, 3);
      expect(permanentFailChunk, isNotNull);
      expect(permanentFailChunk!.attempts, 3);
      expect(queue.queuedCount, 0, reason: 'Chunk must be discarded after maxAttempts reached');
      expect(queue.status.failedCount, 1);

      queue.dispose();
    });

    test('Bounded buffer capacity & backpressure: drops oldest unacknowledged chunk on queue saturation', () {
      final droppedChunks = <AudioChunk>[];
      final reasons = <String>[];

      final queue = AudioChunkDeliveryQueue(
        maxQueueChunks: 3,
        maxQueueBytes: 5000,
        uploader: (chunk) async {
          // Never completes to simulate paused or stuck network
          return Completer<int>().future;
        },
        onChunkDropped: (chunk, reason) {
          droppedChunks.add(chunk);
          reasons.add(reason);
        },
      );

      // Enqueue up to limit (chunk 0 becomes in-flight, chunks 1 and 2 queued)
      queue.enqueue(createSampleChunk(seq: 0, byteCount: 1000));
      queue.enqueue(createSampleChunk(seq: 1, byteCount: 1000));
      queue.enqueue(createSampleChunk(seq: 2, byteCount: 1000));

      expect(droppedChunks.isEmpty, isTrue);

      // Enqueue chunk 3: queue capacity (3) exceeded, must drop oldest unacknowledged queued chunk (chunk 1)
      queue.enqueue(createSampleChunk(seq: 3, byteCount: 1000));

      expect(droppedChunks.length, 1);
      expect(droppedChunks.first.sequenceNumber, 1);
      expect(reasons.first, contains('Queue capacity saturated'));
      expect(queue.status.droppedCount, 1);

      queue.dispose();
    });

    test('Meeting termination: stop() halts retries and rejects new enqueues', () async {
      int attempts = 0;
      final queue = AudioChunkDeliveryQueue(
        baseBackoff: const Duration(milliseconds: 50),
        uploader: (chunk) async {
          attempts++;
          return 500;
        },
      );

      queue.enqueue(createSampleChunk(seq: 0));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(attempts, 1);

      // Meeting ends
      queue.stop();
      expect(queue.isStopped, isTrue);

      // Further enqueue should be rejected
      final accepted = queue.enqueue(createSampleChunk(seq: 1));
      expect(accepted, isFalse);

      // Wait past the retry delay
      await Future<void>.delayed(const Duration(milliseconds: 150));
      expect(attempts, 1, reason: 'No further network attempts after stop()');

      queue.dispose();
    });

    test('Observability: status accurately reports degraded state during retries', () async {
      final statuses = <AudioQueueStatus>[];
      final queue = AudioChunkDeliveryQueue(
        baseBackoff: const Duration(milliseconds: 50),
        uploader: (chunk) async {
          return 500;
        },
        onStatusChanged: (status) {
          statuses.add(status);
        },
      );

      queue.enqueue(createSampleChunk(seq: 0));
      await Future<void>.delayed(const Duration(milliseconds: 20));

      expect(statuses.any((s) => s.queuedCount > 0), isTrue);
      expect(queue.status.lastError, contains('500'));

      queue.dispose();
    });
  });
}
