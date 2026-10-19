import 'dart:convert';
import 'package:flutter/material.dart';

import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';

class TranscriptSegment {
  final String? segmentId;
  final String? recordingId;
  final String speakerLabel;
  final double startTime;
  final double endTime;
  final String text;
  final String? translatedText;
  final String? language;
  final double? confidence;
  final String? userName; // Mapped user name if available
  final bool speakerConfirmed; // Whether speaker mapping is confirmed

  TranscriptSegment({
    this.segmentId,
    this.recordingId,
    required this.speakerLabel,
    required this.startTime,
    required this.endTime,
    required this.text,
    this.translatedText,
    this.language,
    this.confidence,
    this.userName,
    this.speakerConfirmed = false,
  });

  factory TranscriptSegment.fromJson(Map<String, dynamic> json) {
    return TranscriptSegment(
      segmentId: json['segment_id']?.toString(),
      recordingId: json['recording_id']?.toString(),
      speakerLabel: json['speaker_label'] ?? 'Speaker',
      startTime: (json['start_time'] is num) ? (json['start_time'] as num).toDouble() : 0.0,
      endTime: (json['end_time'] is num) ? (json['end_time'] as num).toDouble() : 0.0,
      text: json['text'] ?? '',
      translatedText: json['translated_text'],
      language: json['language'],
      confidence: (json['confidence'] is num) ? (json['confidence'] as num).toDouble() : null,
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
  List<TranscriptSegment> _segments = [];
  bool _isLoading = true;
  String? _errorMessage;
  int? _errorStatusCode;
  String _transcriptionStatus = 'unknown';
  String? _transcriptionError;

  @override
  void initState() {
    super.initState();
    _loadTranscript();
  }

  Future<void> _loadTranscript() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _errorStatusCode = null;
    });

    try {
      final api = ApiService();

      // 1. Fetch transcription processing status
      final statusResp = await api.get('/transcripts/meetings/${widget.meetingId}/status');

      if (statusResp.statusCode == 401) {
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 401;
          _errorMessage = 'Session expired. Please sign in again to access this transcript.';
        });
        return;
      }

      if (statusResp.statusCode == 403) {
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 403;
          _errorMessage = 'Access denied. You are not authorized to view this meeting transcript.';
        });
        return;
      }

      if (statusResp.statusCode == 404) {
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = 404;
          _errorMessage = 'Meeting not found or transcript does not exist.';
        });
        return;
      }

      if (statusResp.statusCode != 200) {
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorStatusCode = statusResp.statusCode;
          _errorMessage = 'Failed to load transcription status (${statusResp.statusCode}).';
        });
        return;
      }

      final statusData = json.decode(statusResp.body);
      final status = (statusData['status'] ?? 'unknown').toString().toLowerCase();
      final err = statusData['error'] as String?;

      _transcriptionStatus = status;
      _transcriptionError = err;

      // 2. If status is completed (or has segments), fetch the segments
      if (status == 'completed') {
        final transcriptResp = await api.get('/transcripts/meetings/${widget.meetingId}');
        if (transcriptResp.statusCode == 200) {
          final data = json.decode(transcriptResp.body);
          final rawSegments = (data['segments'] as List?) ?? [];
          final parsed = rawSegments
              .map((s) => TranscriptSegment.fromJson(s as Map<String, dynamic>))
              .toList();

          // Ensure strict chronological sorting by start time
          parsed.sort((a, b) => a.startTime.compareTo(b.startTime));

          if (!mounted) return;
          setState(() {
            _segments = parsed;
            _isLoading = false;
          });
          return;
        } else if (transcriptResp.statusCode == 401) {
          if (!mounted) return;
          setState(() {
            _isLoading = false;
            _errorStatusCode = 401;
            _errorMessage = 'Session expired. Please sign in again.';
          });
          return;
        } else if (transcriptResp.statusCode == 403) {
          if (!mounted) return;
          setState(() {
            _isLoading = false;
            _errorStatusCode = 403;
            _errorMessage = 'Access denied. You are not authorized to view this meeting transcript.';
          });
          return;
        } else {
          if (!mounted) return;
          setState(() {
            _isLoading = false;
            _errorStatusCode = transcriptResp.statusCode;
            _errorMessage = 'Failed to load transcript data (${transcriptResp.statusCode}).';
          });
          return;
        }
      }

      if (status == 'failed') {
        if (!mounted) return;
        setState(() {
          _isLoading = false;
          _errorMessage = _transcriptionError != null && _transcriptionError!.isNotEmpty
              ? 'Transcription failed: $_transcriptionError'
              : 'Transcription processing failed for this recording.';
        });
        return;
      }

      // If pending, queued, or processing
      if (!mounted) return;
      setState(() {
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      final errStr = e.toString().toLowerCase();
      String userFriendlyMessage = 'An error occurred while loading the transcript.';
      if (errStr.contains('socket') ||
          errStr.contains('network') ||
          errStr.contains('clientexception') ||
          errStr.contains('failed host lookup') ||
          errStr.contains('connection refused')) {
        userFriendlyMessage = 'Network connection offline or unreachable. Please check your internet connection.';
      } else {
        userFriendlyMessage = e.toString().replaceFirst('Exception: ', '');
      }
      setState(() {
        _isLoading = false;
        _errorMessage = userFriendlyMessage;
      });
    }
  }

  String _formatTime(double seconds) {
    if (seconds < 0) seconds = 0;
    final totalSecs = seconds.floor();
    final mins = totalSecs ~/ 60;
    final secs = totalSecs % 60;
    return '${mins.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
  }

  String _getSpeakerDisplay(TranscriptSegment segment) {
    if (segment.userName != null && segment.userName!.trim().isNotEmpty) {
      return segment.userName!.trim();
    }
    return segment.speakerLabel;
  }

  Color _getConfidenceColor(double confidence) {
    if (confidence >= 0.85) return const Color(0xFF16A34A);
    if (confidence >= 0.65) return const Color(0xFFD97706);
    return const Color(0xFFDC2626);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF8FAFC),
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.meetingTitle ?? 'Meeting Transcript',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            Text(
              'ID: ${widget.meetingId}',
              style: const TextStyle(fontSize: 12, color: Colors.grey),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh Transcript',
            onPressed: _isLoading ? null : _loadTranscript,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(strokeWidth: 3),
            SizedBox(height: 16),
            Text(
              'Loading meeting transcript...',
              style: TextStyle(fontSize: 15, color: Color(0xFF64748B), fontWeight: FontWeight.w500),
            ),
          ],
        ),
      );
    }

    // 401 Session Expired State
    if (_errorStatusCode == 401) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFFEF2F2), shape: BoxShape.circle),
                child: const Icon(Icons.lock_clock, size: 48, color: Color(0xFFDC2626)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Session Expired',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              Text(
                _errorMessage ?? 'Your session has expired. Please log in again to continue.',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: () => Navigator.pushNamedAndRemoveUntil(context, AppRouter.login, (r) => false),
                icon: const Icon(Icons.login),
                label: const Text('Go to Login'),
              ),
            ],
          ),
        ),
      );
    }

    // 403 Inaccessible Meeting State
    if (_errorStatusCode == 403) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFFFFBEB), shape: BoxShape.circle),
                child: const Icon(Icons.shield_outlined, size: 48, color: Color(0xFFD97706)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Access Denied',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              Text(
                _errorMessage ?? 'You do not have permission to access this meeting transcript.',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              OutlinedButton.icon(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.arrow_back),
                label: const Text('Back to Meetings'),
              ),
            ],
          ),
        ),
      );
    }

    // General Error / Offline State with Safe Retry
    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFFEF2F2), shape: BoxShape.circle),
                child: const Icon(Icons.error_outline, size: 48, color: Color(0xFFDC2626)),
              ),
              const SizedBox(height: 20),
              const Text(
                'Unable to Load Transcript',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              Text(
                _errorMessage!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: _loadTranscript,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    // Queued / Processing / Pending States
    if (_transcriptionStatus == 'pending' ||
        _transcriptionStatus == 'queued' ||
        _transcriptionStatus == 'processing') {
      final isQueued = _transcriptionStatus == 'queued';
      final isPending = _transcriptionStatus == 'pending';
      final title = isPending
          ? 'Transcription Pending'
          : isQueued
              ? 'Transcription Queued'
              : 'Transcribing Audio...';
      final subtitle = isPending
          ? 'Audio is queued for processing. When processing starts, recognized speech will appear here.'
          : isQueued
              ? 'Recording is in queue for the speech recognition worker.'
              : 'AI is recognizing multilingual speech and speaker diarization. Please stand by.';

      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Card(
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: const BorderSide(color: Color(0xFFFDE68A)),
            ),
            color: const Color(0xFFFFFBEB),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const SizedBox(
                    width: 48,
                    height: 48,
                    child: CircularProgressIndicator(strokeWidth: 3, color: Color(0xFFB45309)),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    title,
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFF92400E),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    subtitle,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 13, color: Color(0xFFB45309)),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.tonalIcon(
                    onPressed: _loadTranscript,
                    icon: const Icon(Icons.refresh, size: 18),
                    label: const Text('Refresh Status'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    // Empty Transcript State
    if (_segments.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: const BoxDecoration(color: Color(0xFFF1F5F9), shape: BoxShape.circle),
                child: const Icon(Icons.record_voice_over_outlined, size: 48, color: Color(0xFF94A3B8)),
              ),
              const SizedBox(height: 20),
              const Text(
                'No Transcript Segments Found',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF0F172A)),
              ),
              const SizedBox(height: 8),
              const Text(
                'No speech was detected or recorded for this meeting.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 14, color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 24),
              OutlinedButton.icon(
                onPressed: _loadTranscript,
                icon: const Icon(Icons.refresh),
                label: const Text('Check Again'),
              ),
            ],
          ),
        ),
      );
    }

    // Completed Transcript List - Virtualized for Long Transcripts
    return RefreshIndicator(
      onRefresh: _loadTranscript,
      child: ListView.builder(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        itemCount: _segments.length,
        itemBuilder: (context, index) {
          final segment = _segments[index];
          final speakerDisplay = _getSpeakerDisplay(segment);
          final hasUserMapping = segment.userName != null && segment.userName!.trim().isNotEmpty;
          final hasTranslation = segment.translatedText != null &&
              segment.translatedText!.trim().isNotEmpty &&
              segment.translatedText!.trim() != segment.text.trim();

          return Card(
            margin: const EdgeInsets.only(bottom: 12),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
              side: const BorderSide(color: Color(0xFFE2E8F0)),
            ),
            color: Colors.white,
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Header Row: Speaker, Time Range, Language, Confidence
                  Row(
                    children: [
                      // Speaker Label Chip
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                        decoration: BoxDecoration(
                          color: hasUserMapping ? const Color(0xFFECFDF5) : const Color(0xFFEFF6FF),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                            color: hasUserMapping ? const Color(0xFFA7F3D0) : const Color(0xFFBFDBFE),
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(
                              hasUserMapping ? Icons.person : Icons.mic_none,
                              size: 13,
                              color: hasUserMapping ? const Color(0xFF047857) : const Color(0xFF1D4ED8),
                            ),
                            const SizedBox(width: 5),
                            Text(
                              speakerDisplay,
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.bold,
                                color: hasUserMapping ? const Color(0xFF047857) : const Color(0xFF1D4ED8),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 10),

                      // Timestamp Range
                      Text(
                        '${_formatTime(segment.startTime)} – ${_formatTime(segment.endTime)}',
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF64748B),
                        ),
                      ),
                      const Spacer(),

                      // Detected Language Tag (if available)
                      if (segment.language != null && segment.language!.isNotEmpty) ...[
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: const Color(0xFFF1F5F9),
                            borderRadius: BorderRadius.circular(6),
                            border: Border.all(color: const Color(0xFFCBD5E1)),
                          ),
                          child: Text(
                            segment.language!.toUpperCase(),
                            style: const TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              color: Color(0xFF475569),
                            ),
                          ),
                        ),
                        const SizedBox(width: 6),
                      ],

                      // Confidence Badge (if available)
                      if (segment.confidence != null)
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: _getConfidenceColor(segment.confidence!).withOpacity(0.12),
                            borderRadius: BorderRadius.circular(6),
                            border: Border.all(
                              color: _getConfidenceColor(segment.confidence!).withOpacity(0.3),
                            ),
                          ),
                          child: Text(
                            '${(segment.confidence! * 100).toStringAsFixed(0)}%',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              color: _getConfidenceColor(segment.confidence!),
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 10),

                  // Original Recognized Speech Text
                  SelectableText(
                    segment.text,
                    style: const TextStyle(
                      fontSize: 15,
                      height: 1.45,
                      color: Color(0xFF1E293B),
                    ),
                  ),

                  // Optional Translated Text Callout
                  if (hasTranslation) ...[
                    const SizedBox(height: 10),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: const Color(0xFFF8FAFC),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: const Color(0xFFE2E8F0)),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.translate, size: 14, color: Color(0xFF64748B)),
                          const SizedBox(width: 8),
                          Expanded(
                            child: SelectableText(
                              segment.translatedText!,
                              style: const TextStyle(
                                fontSize: 14,
                                fontStyle: FontStyle.italic,
                                color: Color(0xFF334155),
                                height: 1.4,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}
