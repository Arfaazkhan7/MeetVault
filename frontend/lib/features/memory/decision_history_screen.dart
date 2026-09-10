import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class DecisionHistoryScreen extends StatelessWidget {
  const DecisionHistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Decision History',
      currentRoute: AppRouter.projectMemory,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            color: Theme.of(context).colorScheme.tertiaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Icon(
                    Icons.history,
                    size: 32,
                    color: Theme.of(context).colorScheme.onTertiaryContainer,
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Decision Evolution Chain',
                          style: Theme.of(context).textTheme.titleLarge?.copyWith(
                                color: Theme.of(context).colorScheme.onTertiaryContainer,
                                fontWeight: FontWeight.bold,
                              ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Preserves full decision history across meetings: Proposal → Concern → Alternative → Final Decision with chronological evidence.',
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                color: Theme.of(context).colorScheme.onTertiaryContainer,
                              ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Example Evolution Chain Display
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Decision: System Architecture Selection',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      const Chip(label: Text('FINAL DECISION: ECS'), backgroundColor: Colors.greenAccent),
                      const SizedBox(width: 8),
                      Text('Source: 4 meetings', style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                  const Divider(height: 24),

                  // Stage 1: Proposal
                  _buildChainNode(
                    context,
                    stage: 'PROPOSAL',
                    stageColor: Colors.blue,
                    meeting: 'Meeting 1',
                    text: 'Proposal: The team proposes AWS Lambda.',
                  ),
                  // Stage 2: Concern
                  _buildChainNode(
                    context,
                    stage: 'CONCERN',
                    stageColor: Colors.orange,
                    meeting: 'Meeting 2',
                    text: 'Concern: The team raises concerns about cold-start latency.',
                  ),
                  // Stage 3: Alternative
                  _buildChainNode(
                    context,
                    stage: 'ALTERNATIVE',
                    stageColor: Colors.purple,
                    meeting: 'Meeting 3',
                    text: 'Alternative: The team proposes ECS as an alternative.',
                  ),
                  // Stage 4: Final Decision
                  _buildChainNode(
                    context,
                    stage: 'FINAL DECISION',
                    stageColor: Colors.green,
                    meeting: 'Meeting 4',
                    text: 'Final Decision: The team selects ECS.',
                  ),

                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.surfaceVariant,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.info_outline, size: 20),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Reason Evidence: Selected ECS to avoid serverless cold-start latency while maintaining container portability.',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildChainNode(
    BuildContext context, {
    required String stage,
    required Color stageColor,
    required String meeting,
    required String text,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: stageColor.withOpacity(0.2),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: stageColor),
            ),
            child: Text(
              stage,
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: stageColor),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(meeting, style: TextStyle(fontSize: 11, color: Theme.of(context).colorScheme.secondary, fontWeight: FontWeight.w600)),
                Text(text, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
