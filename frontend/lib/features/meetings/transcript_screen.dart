import 'package:flutter/material.dart';
import 'dart:convert';

import '../../core/services/api_service.dart';

class TranscriptSegment {
  final String speakerLabel;
  final double startTime;
  final double endTime;
  final String text;
  final String? language;
  final double? confidence;
  final String? userName;  // Mapped user name if available
  final bool speakerConfirmed;  // Whether speaker mapping is confirmed

  TranscriptSegment({
    required this.speakerLabel,
    required this.startTime,
    required this.endTime,
    required this.text,
    this.language,
    this.confidence,
    this.userName,
    this.speakerConfirmed = false,
  });

  factory TranscriptSegment.fromJson(Map<String, dynamic> json) {
    return TranscriptSegment(
      speakerLabel: json['speaker_label'] ?? 'Unknown',
      startTime: (json['start_time'] ?? 0).toDouble(),
      endTime: (json['end_time'] ?? 0).toDouble(),
      text: json['text'] ?? '',
      language: json['language'],
      confidence: json['confidence']?.toDouble(),
      userName: json['user_name'],
      speakerConfirmed: json['speaker_confirmed'] ?? false,
    );
  }
}

class TranscriptScreen extends StatefulWidget {
  final String meetingId;
  final String? meetingTitle;

  const TranscriptScreen({
    super.key,
    required this.meetingId,
    this.meetingTitle,
  });

  @override
  State<TranscriptScreen> createState() => _TranscriptScreenState();
}

class _TranscriptScreenState extends State<TranscriptScreen> {
  List<TranscriptSegment> segments = [];
  Map<String, String> speakerNames = {};  // SPEAKER_00 -> "John Doe"
  bool isLoading = true;
  String? errorMessage;
  String transcriptionStatus = 'unknown';

  @override
  void initState() {
    super.initState();
    _loadTranscript();
  }

  Future<void> _loadTranscript() async {
    setState(() {
      isLoading = true;
      errorMessage = null;
    });

    try {
      // Load speaker mappings first
      await _loadSpeakerMappings();
      
      // Then check status
      final response = await ApiService().get('/transcripts/meetings/${widget.meetingId}/status');
      final statusResponse = response;

      if (statusResponse.statusCode == 200) {
        final statusData = json.decode(statusResponse.body);
        setState(() {
          transcriptionStatus = statusData['status'] ?? 'unknown';
        });

        // If completed, load transcript
        if (transcriptionStatus == 'completed') {
          final transcriptResponse = await ApiService().get('/transcripts/meetings/${widget.meetingId}');

          if (transcriptResponse.statusCode == 200) {
            final data = json.decode(transcriptResponse.body);
            final segmentsList = data['segments'] as List;
            
            setState(() {
              segments = segmentsList
                  .map((seg) => TranscriptSegment.fromJson(seg))
                  .toList();
              isLoading = false;
            });
          } else {
            setState(() {
              errorMessage = 'Failed to load transcript';
              isLoading = false;
            });
          }
        } else if (transcriptionStatus == 'failed') {
          setState(() {
            errorMessage = 'Transcription failed';
            isLoading = false;
          });
        } else {
          // Still processing
          setState(() {
            isLoading = false;
          });
        }
      } else {
        setState(() {
          errorMessage = 'Failed to check transcription status';
          isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        errorMessage = 'Error: $e';
        isLoading = false;
      });
    }
  }

  Future<void> _loadSpeakerMappings() async {
    try {
      final response = await ApiService().get('/diarization/meetings/${widget.meetingId}/speaker-mappings');

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final mappings = data['mappings'] as List;
        
        setState(() {
          for (var mapping in mappings) {
            if (mapping['user_name'] != null) {
              speakerNames[mapping['speaker_label']] = mapping['user_name'];
            }
          }
        });
      }
    } catch (e) {
      // Speaker mappings might not exist yet, that's okay
      print('Failed to load speaker mappings: $e');
    }
  }

  String _formatTime(double seconds) {
    final minutes = (seconds / 60).floor();
    final secs = (seconds % 60).floor();
    return '${minutes.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
  }

  String _getSpeakerDisplay(TranscriptSegment segment) {
    // Return user name if mapped and confirmed, otherwise show speaker label
    if (segment.userName != null && segment.speakerConfirmed) {
      return segment.userName!;
    }
    return segment.speakerLabel;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.meetingTitle ?? 'Meeting Transcript'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadTranscript,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (isLoading) {
      return const Center(
        child: CircularProgressIndicator(),
      );
    }

    if (errorMessage != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 16),
            Text(
              errorMessage!,
              style: const TextStyle(color: Colors.red),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadTranscript,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (transcriptionStatus == 'pending' || transcriptionStatus == 'queued' || transcriptionStatus == 'processing') {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const CircularProgressIndicator(),
            const SizedBox(height: 16),
            Text(
              'Transcription ${transcriptionStatus}',
              style: const TextStyle(fontSize: 16),
            ),
            const SizedBox(height: 8),
            const Text('Please wait...'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadTranscript,
              child: const Text('Refresh'),
            ),
          ],
        ),
      );
    }

    if (segments.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.chat_bubble_outline, size: 48, color: Colors.grey),
            const SizedBox(height: 16),
            const Text('No transcript available'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadTranscript,
              child: const Text('Refresh'),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: segments.length,
      itemBuilder: (context, index) {
        final segment = segments[index];
        final speakerDisplay = _getSpeakerDisplay(segment);
        final hasUserMapping = segment.userName != null;
        
        return Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: hasUserMapping 
                            ? Colors.green.shade100 
                            : Colors.blue.shade100,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            hasUserMapping ? Icons.person : Icons.mic,
                            size: 14,
                            color: hasUserMapping 
                                ? Colors.green.shade800 
                                : Colors.blue.shade800,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            speakerDisplay,
                            style: TextStyle(
                              color: hasUserMapping 
                                  ? Colors.green.shade800 
                                  : Colors.blue.shade800,
                              fontWeight: FontWeight.bold,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '${_formatTime(segment.startTime)} - ${_formatTime(segment.endTime)}',
                      style: TextStyle(
                        color: Colors.grey.shade600,
                        fontSize: 12,
                      ),
                    ),
                    if (segment.confidence != null) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: _getConfidenceColor(segment.confidence!),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          '${(segment.confidence! * 100).toStringAsFixed(0)}%',
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  segment.text,
                  style: const TextStyle(fontSize: 15),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Color _getConfidenceColor(double confidence) {
    if (confidence >= 0.8) return Colors.green;
    if (confidence >= 0.6) return Colors.orange;
    return Colors.red;
  }
}
