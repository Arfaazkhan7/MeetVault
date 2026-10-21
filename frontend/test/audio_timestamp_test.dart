import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_meeting_system/features/meetings/transcript_screen.dart';

void main() {
  group('Audio Chunk Sample Clock & Offset Calculations', () {
    const sampleRate = 16000;
    const bytesPerFrame = 2; // 16-bit mono PCM

    test('Accurately computes chunk duration and offsets from PCM frame count', () {
      // 1.0 second of audio at 16kHz 16-bit mono = 32000 bytes
      const frameBytes1s = 32000;
      final samples1s = frameBytes1s ~/ bytesPerFrame;
      final duration1s = samples1s / sampleRate;
      expect(duration1s, 1.0);

      // Session start offset = 5.2 seconds into meeting
      const sessionStartOffset = 5.200;
      int totalStreamedSamples = 0;

      // Chunk 0: 32000 bytes (1.0s)
      final startOffset0 = sessionStartOffset + (totalStreamedSamples / sampleRate);
      final endOffset0 = startOffset0 + duration1s;
      expect(startOffset0, closeTo(5.200, 0.001));
      expect(endOffset0, closeTo(6.200, 0.001));
      totalStreamedSamples += samples1s;

      // Chunk 1: 48000 bytes (1.5s)
      const frameBytes1_5s = 48000;
      final samples1_5s = frameBytes1_5s ~/ bytesPerFrame;
      final duration1_5s = samples1_5s / sampleRate;
      expect(duration1_5s, 1.5);

      final startOffset1 = sessionStartOffset + (totalStreamedSamples / sampleRate);
      final endOffset1 = startOffset1 + duration1_5s;
      expect(startOffset1, closeTo(6.200, 0.001));
      expect(endOffset1, closeTo(7.700, 0.001));
      totalStreamedSamples += samples1_5s;

      // Chunk 2: 16000 bytes (0.5s)
      const frameBytes0_5s = 16000;
      final samples0_5s = frameBytes0_5s ~/ bytesPerFrame;
      final duration0_5s = samples0_5s / sampleRate;
      final startOffset2 = sessionStartOffset + (totalStreamedSamples / sampleRate);
      final endOffset2 = startOffset2 + duration0_5s;
      expect(startOffset2, closeTo(7.700, 0.001));
      expect(endOffset2, closeTo(8.200, 0.001));
    });

    test('Buffer slicing removes complete frames and preserves leftover odd byte', () {
      final buffer = <int>[10, 20, 30, 40, 50]; // 5 bytes (2 full 16-bit frames + 1 leftover byte)
      final totalBytes = buffer.length;
      final frameBytes = totalBytes - (totalBytes % bytesPerFrame);
      expect(frameBytes, 4);

      final chunk = Uint8List.fromList(buffer.sublist(0, frameBytes));
      buffer.removeRange(0, frameBytes);

      expect(chunk.length, 4);
      expect(buffer.length, 1);
      expect(buffer.first, 50); // Leftover preserved for next frame
    });

    test('TranscriptSegment parses sample-accurate timing and metadata', () {
      final json = {
        'segment_id': 'mtg-test_part-1_10000',
        'speaker_label': 'SPEAKER_usr-1',
        'speaker_user_id': 'usr-1',
        'user_id': 'usr-1',
        'attribution_status': 'verified',
        'start_time': 10.000,
        'end_time': 12.450,
        'text': 'This is a sample-accurate transcribed sentence.',
        'speaker_confirmed': true,
        'processing_metadata': {
          'timing_source': 'audio_sample_clock',
          'sequence_number': 3,
          'chunk_start_offset': 10.0,
          'chunk_end_offset': 14.0,
          'sample_rate': 16000,
          'frame_count': 64000,
        },
      };

      final segment = TranscriptSegment.fromJson(json);
      expect(segment.startTime, 10.0);
      expect(segment.endTime, 12.450);
      expect(segment.speakerConfirmed, isTrue);
      expect(segment.attributionStatus, 'verified');
    });
  });
}
