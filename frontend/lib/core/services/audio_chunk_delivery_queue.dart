import 'dart:async';
import 'dart:math';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';

/// Represents a discrete, immutable audio chunk ready for delivery to MeetVault.
class AudioChunk {
  final String chunkId;
  final int sequenceNumber;
  final String meetingId;
  final String participantId;
  final Uint8List wavBytes;
  final double startOffset;
  final double endOffset;
  final double duration;
  final int sampleRate;
  final DateTime createdAt;

  int attempts = 0;
  DateTime? lastAttemptAt;
  DateTime? nextRetryAt;
  String? lastError;
  bool isAcknowledged = false;

  AudioChunk({
    required this.chunkId,
    required this.sequenceNumber,
    required this.meetingId,
    required this.participantId,
    required this.wavBytes,
    required this.startOffset,
    required this.endOffset,
    required this.duration,
    required this.sampleRate,
    DateTime? createdAt,
  }) : createdAt = createdAt ?? DateTime.now();

  int get byteSize => wavBytes.length;
}

/// Status snapshot of the audio delivery queue for monitoring and UI feedback.
class AudioQueueStatus {
  final int queuedCount;
  final int queuedBytes;
  final int inFlightCount;
  final int deliveredCount;
  final int failedCount;
  final int droppedCount;
  final bool isDegraded;
  final String? lastError;

  const AudioQueueStatus({
    this.queuedCount = 0,
    this.queuedBytes = 0,
    this.inFlightCount = 0,
    this.deliveredCount = 0,
    this.failedCount = 0,
    this.droppedCount = 0,
    this.isDegraded = false,
    this.lastError,
  });

  @override
  String toString() {
    return 'AudioQueueStatus(queued: $queuedCount ($queuedBytes bytes), delivered: $deliveredCount, failed: $failedCount, dropped: $droppedCount, degraded: $isDegraded)';
  }
}

/// Type definition for audio chunk upload operation.
/// Returns HTTP status code (e.g. 201 for success).
typedef ChunkUploader = Future<int> Function(AudioChunk chunk);

/// Manages reliable, sequential, bounded audio chunk delivery with exponential backoff retries.
class AudioChunkDeliveryQueue {
  final ChunkUploader uploader;
  final int maxQueueBytes;
  final int maxQueueChunks;
  final int maxAttempts;
  final Duration baseBackoff;
  final Duration maxBackoff;

  final List<AudioChunk> _queue = <AudioChunk>[];
  Timer? _retryTimer;
  bool _isProcessing = false;
  bool _isStopped = false;
  AudioChunk? _currentInFlight;

  int _deliveredCount = 0;
  int _failedCount = 0;
  int _droppedCount = 0;
  String? _lastError;

  // Callbacks
  void Function(AudioQueueStatus status)? onStatusChanged;
  void Function(AudioChunk chunk)? onChunkDelivered;
  void Function(AudioChunk chunk, String reason)? onChunkDropped;
  void Function(AudioChunk chunk, String error)? onPermanentFailure;

  AudioChunkDeliveryQueue({
    required this.uploader,
    this.maxQueueBytes = 2 * 1024 * 1024, // 2MB (~65s of 16kHz 16-bit mono PCM)
    this.maxQueueChunks = 15,
    this.maxAttempts = 5,
    this.baseBackoff = const Duration(milliseconds: 1000),
    this.maxBackoff = const Duration(seconds: 16),
    this.onStatusChanged,
    this.onChunkDelivered,
    this.onChunkDropped,
    this.onPermanentFailure,
  });

  int get totalQueuedBytes => _queue.fold(0, (sum, c) => sum + c.byteSize);
  int get queuedCount => _queue.length;
  bool get isProcessing => _isProcessing;
  bool get isStopped => _isStopped;

  AudioQueueStatus get status => AudioQueueStatus(
        queuedCount: _queue.length,
        queuedBytes: totalQueuedBytes,
        inFlightCount: _currentInFlight != null ? 1 : 0,
        deliveredCount: _deliveredCount,
        failedCount: _failedCount,
        droppedCount: _droppedCount,
        isDegraded: _queue.any((c) => c.attempts > 1),
        lastError: _lastError,
      );

  /// Enqueue an audio chunk for delivery.
  /// If the bounded queue capacity is exceeded, applies safe backpressure:
  /// drops the oldest unacknowledged chunk to prevent unbounded memory growth.
  bool enqueue(AudioChunk chunk) {
    if (_isStopped) {
      debugPrint('[AudioDeliveryQueue] Cannot enqueue chunk #${chunk.sequenceNumber}: queue is stopped');
      return false;
    }

    // Check bounded queue capacity limits
    while (_queue.isNotEmpty &&
        (totalQueuedBytes + chunk.byteSize > maxQueueBytes || _queue.length >= maxQueueChunks)) {
      // If the head chunk is currently actively transmitting over network, preserve it and drop the oldest pending queued chunk
      final dropIndex = (_currentInFlight != null && _queue.isNotEmpty && _queue.first == _currentInFlight && _queue.length > 1)
          ? 1
          : 0;
      final dropped = _queue.removeAt(dropIndex);
      _droppedCount++;
      debugPrint('[AudioDeliveryQueue] Queue saturation: dropped oldest chunk #${dropped.sequenceNumber} (${dropped.byteSize} bytes)');
      onChunkDropped?.call(dropped, 'Queue capacity saturated (backpressure limit reached)');
    }

    _queue.add(chunk);
    _notifyStatus();
    _scheduleProcessing();
    return true;
  }

  void _scheduleProcessing() {
    if (_isProcessing || _isStopped || _queue.isEmpty) return;

    final head = _queue.first;
    if (head.nextRetryAt != null) {
      final now = DateTime.now();
      if (now.isBefore(head.nextRetryAt!)) {
        final waitDuration = head.nextRetryAt!.difference(now);
        _retryTimer?.cancel();
        _retryTimer = Timer(waitDuration, () {
          _retryTimer = null;
          _scheduleProcessing();
        });
        return;
      }
    }

    _processHeadChunk();
  }

  Future<void> _processHeadChunk() async {
    if (_isProcessing || _isStopped || _queue.isEmpty) return;
    _isProcessing = true;

    final chunk = _queue.first;
    _currentInFlight = chunk;
    chunk.attempts++;
    chunk.lastAttemptAt = DateTime.now();
    _notifyStatus();

    try {
      final statusCode = await uploader(chunk);

      if (_isStopped) {
        _isProcessing = false;
        _currentInFlight = null;
        return;
      }

      if (statusCode == 200 || statusCode == 201) {
        // Success: acknowledgment received from server
        chunk.isAcknowledged = true;
        _queue.remove(chunk);
        _deliveredCount++;
        _lastError = null;
        onChunkDelivered?.call(chunk);
      } else if (_isPermanentFailure(statusCode)) {
        // Permanent failure (e.g. 400 Bad Request, 403 Forbidden, 404 Not Found)
        // Must not retry indefinitely to avoid battery drain and queue clogging
        _queue.remove(chunk);
        _failedCount++;
        _lastError = 'Permanent HTTP $statusCode error';
        onPermanentFailure?.call(chunk, _lastError!);
      } else {
        // Retryable status code (e.g. 500, 502, 503, 504, 429)
        _handleRetryableFailure(chunk, 'Server error (HTTP $statusCode)');
      }
    } catch (e) {
      if (_isStopped) {
        _isProcessing = false;
        _currentInFlight = null;
        return;
      }
      _handleRetryableFailure(chunk, e.toString());
    } finally {
      _currentInFlight = null;
      _isProcessing = false;
      _notifyStatus();
      if (!_isStopped && _queue.isNotEmpty) {
        _scheduleProcessing();
      }
    }
  }

  bool _isPermanentFailure(int statusCode) {
    // 400 Bad Request (malformed audio/offsets), 401 Unauthorized (invalid auth), 403 Forbidden, 404 Not Found
    return statusCode == 400 || statusCode == 401 || statusCode == 403 || statusCode == 404;
  }

  void _handleRetryableFailure(AudioChunk chunk, String error) {
    chunk.lastError = error;
    _lastError = error;

    if (chunk.attempts >= maxAttempts) {
      debugPrint('[AudioDeliveryQueue] Chunk #${chunk.sequenceNumber} exceeded max attempts ($maxAttempts): failing permanently');
      _queue.remove(chunk);
      _failedCount++;
      onPermanentFailure?.call(chunk, 'Exceeded max retry attempts ($maxAttempts): $error');
      return;
    }

    // Bounded exponential backoff with random jitter (+/- 20%)
    final attemptIndex = chunk.attempts - 1;
    final delayMs = (baseBackoff.inMilliseconds * pow(2, attemptIndex)).toInt().clamp(0, maxBackoff.inMilliseconds);
    final jitterFactor = 0.2 * (Random().nextDouble() * 2 - 1); // -0.2 to +0.2
    final jitteredDelayMs = (delayMs + (delayMs * jitterFactor)).toInt().clamp(0, maxBackoff.inMilliseconds);
    final retryDelay = Duration(milliseconds: jitteredDelayMs);

    chunk.nextRetryAt = DateTime.now().add(retryDelay);
    debugPrint('[AudioDeliveryQueue] Chunk #${chunk.sequenceNumber} delivery failed (attempt ${chunk.attempts}/$maxAttempts). Next retry in ${retryDelay.inMilliseconds}ms');
  }

  void _notifyStatus() {
    onStatusChanged?.call(status);
  }

  /// Stop the queue, cancel any scheduled retry timers, and discard in-flight state.
  /// Called when meeting ends or participant disconnects.
  void stop() {
    _isStopped = true;
    _retryTimer?.cancel();
    _retryTimer = null;
    _isProcessing = false;
    _currentInFlight = null;
    _notifyStatus();
  }

  /// Clear all queued chunks and reset counters.
  void clear() {
    _queue.clear();
    _currentInFlight = null;
    _notifyStatus();
  }

  /// Re-enable the queue if stopped.
  void resume() {
    if (!_isStopped) return;
    _isStopped = false;
    _scheduleProcessing();
  }

  void dispose() {
    stop();
    _queue.clear();
  }
}
