import 'dart:convert';
import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class AskMemoryScreen extends StatefulWidget {
  const AskMemoryScreen({super.key});

  @override
  State<AskMemoryScreen> createState() => _AskMemoryScreenState();
}

class _AskMemoryScreenState extends State<AskMemoryScreen> {
  final _api = ApiService();
  final _questionCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  Map<String, dynamic>? _ragResponse;
  String? _selectedProjectId;
  List<Map<String, dynamic>> _projects = [];

  final List<String> _sampleQuestions = [
    "What did we discuss about authentication?",
    "Why did we change the database architecture?",
    "Who proposed ECS?",
    "What decisions were made about cloud infrastructure?",
    "What tasks are still pending?",
    "How has the project's deployment strategy changed?",
  ];

  @override
  void initState() {
    super.initState();
    _loadProjects();
  }

  Future<void> _loadProjects() async {
    try {
      final res = await _api.get('/projects');
      if (res.statusCode == 200) {
        final List list = json.decode(res.body);
        setState(() {
          _projects = list.cast<Map<String, dynamic>>();
        });
      }
    } catch (_) {}
  }

  Future<void> _askQuestion(String questionText) async {
    if (questionText.trim().isEmpty) return;
    _questionCtrl.text = questionText;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final body = {
        'question': questionText.trim(),
        if (_selectedProjectId != null) 'project_id': _selectedProjectId,
        'limit': 12,
      };

      final res = await _api.post('/rag/ask', body: body);

      if (res.statusCode == 200) {
        setState(() {
          _ragResponse = json.decode(res.body);
          _loading = false;
        });
      } else {
        final errJson = json.decode(res.body);
        setState(() {
          _error = errJson['detail']?.toString() ?? 'Failed to complete RAG query';
          _loading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Ask Meeting Memory',
      currentRoute: AppRouter.askMemory,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildScopeBar(),
          const SizedBox(height: 12),
          _buildQuestionInput(),
          const SizedBox(height: 12),
          _buildSampleChips(),
          const SizedBox(height: 20),
          if (_loading)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: Column(
                  children: [
                    CircularProgressIndicator(),
                    SizedBox(height: 16),
                    Text('Searching meeting memory & synthesizing grounded response...'),
                  ],
                ),
              ),
            )
          else if (_error != null)
            UiState.error(_error!, onRetry: () => _askQuestion(_questionCtrl.text))
          else if (_ragResponse != null)
            _buildAnswerCard()
          else
            const SizedBox(
              height: 220,
              child: UiState.empty('Ask any question about past meeting discussions, topics, decisions, or document text.'),
            ),
        ],
      ),
    );
  }

  Widget _buildScopeBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          const Icon(Icons.filter_alt_outlined, size: 20),
          const SizedBox(width: 8),
          const Text('Knowledge Scope:', style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(width: 12),
          Expanded(
            child: DropdownButtonHideUnderline(
              child: DropdownButton<String?>(
                value: _selectedProjectId,
                isExpanded: true,
                items: [
                  const DropdownMenuItem(value: null, child: Text('Entire Company Memory (All Projects)')),
                  for (final p in _projects)
                    DropdownMenuItem(
                      value: p['public_id'],
                      child: Text('Project: ${p['name'] ?? p['public_id']}'),
                    ),
                ],
                onChanged: (val) => setState(() => _selectedProjectId = val),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildQuestionInput() {
    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          children: [
            TextField(
              controller: _questionCtrl,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(
                hintText: 'e.g. Why did we decide to switch from AWS Lambda to ECS?',
                border: InputBorder.none,
                icon: Icon(Icons.psychology_outlined),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (_questionCtrl.text.isNotEmpty)
                  TextButton(
                    onPressed: () {
                      _questionCtrl.clear();
                      setState(() => _ragResponse = null);
                    },
                    child: const Text('Clear'),
                  ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: _loading ? null : () => _askQuestion(_questionCtrl.text),
                  icon: const Icon(Icons.send),
                  label: const Text('Ask Memory'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSampleChips() {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final q in _sampleQuestions)
          ActionChip(
            avatar: const Icon(Icons.auto_awesome, size: 14),
            label: Text(q, style: const TextStyle(fontSize: 12)),
            onPressed: () => _askQuestion(q),
          ),
      ],
    );
  }

  Widget _buildAnswerCard() {
    final resp = _ragResponse!;
    final answer = resp['answer'] ?? '';
    final insufficient = resp['insufficient_evidence'] ?? false;
    final confidence = (resp['confidence'] as num?)?.toDouble() ?? 0.0;
    final modelUsed = resp['model_used'] ?? 'LLM';
    final evidence = (resp['evidence'] as List? ?? []).cast<Map<String, dynamic>>();
    final ragEval = resp['rag_eval'] as Map<String, dynamic>?;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (insufficient)
          Container(
            padding: const EdgeInsets.all(12),
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              color: Colors.amber.shade100,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.amber.shade600),
            ),
            child: const Row(
              children: [
                Icon(Icons.warning_amber_rounded, color: Colors.amber),
                SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Insufficient meeting memory evidence found to answer this question with high confidence.',
                    style: TextStyle(fontWeight: FontWeight.w500),
                  ),
                ),
              ],
            ),
          ),
        Card(
          elevation: 3,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.auto_awesome, color: Colors.indigo),
                        SizedBox(width: 8),
                        Text('Grounded AI Answer', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                      ],
                    ),
                    Chip(
                      label: Text('Confidence: ${(confidence * 100).toStringAsFixed(0)}%'),
                      backgroundColor: confidence > 0.7 ? Colors.green.shade100 : Colors.orange.shade100,
                    ),
                  ],
                ),
                const Divider(),
                const SizedBox(height: 8),
                SelectableText(
                  answer,
                  style: const TextStyle(fontSize: 15, height: 1.5),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Icon(Icons.memory, size: 14, color: Colors.grey.shade600),
                    const SizedBox(width: 4),
                    Text('Model: $modelUsed', style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
                    const Spacer(),
                    if (ragEval != null) ...[
                      Text('Cited Meetings: ${ragEval['evidence_coverage_meetings'] ?? 0}', style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
                      const SizedBox(width: 12),
                      Text('Avg Similarity: ${((ragEval['avg_evidence_score'] as num?)?.toDouble() ?? 0.0).toStringAsFixed(2)}', style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),
        Text('Cited Evidence (${evidence.length})', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        for (final item in evidence) _buildEvidenceCard(item),
      ],
    );
  }

  String _formatTime(double? seconds) {
    if (seconds == null) return '';
    final totalSec = seconds.toInt();
    final m = totalSec ~/ 60;
    final s = totalSec % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  Widget _buildEvidenceCard(Map<String, dynamic> item) {
    final sourceType = item['source_type'] ?? 'evidence';
    final title = item['meeting_title'] ?? item['source_id'] ?? 'Meeting Evidence';
    final speaker = item['speaker'];
    final excerpt = item['excerpt'] ?? '';
    final score = (item['score'] as num?)?.toDouble() ?? 0.0;
    final meetingId = item['meeting_id']?.toString();
    final startTime = (item['start_time'] as num?)?.toDouble();
    final endTime = (item['end_time'] as num?)?.toDouble();
    final timeStr = startTime != null ? '${_formatTime(startTime)}${endTime != null ? " - ${_formatTime(endTime)}" : ""}' : '';

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ExpansionTile(
        leading: Icon(
          sourceType == 'decision' ? Icons.fact_check : sourceType == 'topic' ? Icons.topic : Icons.record_voice_over,
          color: Colors.blue.shade700,
        ),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
        subtitle: Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 8,
          children: [
            Text(
              'Type: ${sourceType.replaceAll('_', ' ')} ${speaker != null ? "• Speaker: $speaker" : ""}',
              style: const TextStyle(fontSize: 12),
            ),
            if (timeStr.isNotEmpty)
              Text('⏱ $timeStr', style: const TextStyle(fontSize: 11, color: Colors.indigo, fontWeight: FontWeight.bold)),
          ],
        ),
        trailing: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(color: Colors.blue.shade50, borderRadius: BorderRadius.circular(6)),
          child: Text('Score: ${score.toStringAsFixed(2)}', style: TextStyle(fontSize: 12, color: Colors.blue.shade900)),
        ),
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SelectableText(
                  excerpt,
                  style: const TextStyle(fontStyle: FontStyle.italic, fontSize: 13),
                ),
                if (meetingId != null && meetingId.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton.icon(
                      onPressed: () {
                        Navigator.pushNamed(
                          context,
                          '/meetings/$meetingId/transcript',
                          arguments: {'title': title},
                        );
                      },
                      icon: const Icon(Icons.open_in_new, size: 14),
                      label: const Text('View in Transcript'),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
