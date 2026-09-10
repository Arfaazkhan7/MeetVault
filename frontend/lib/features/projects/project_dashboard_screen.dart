import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/api_collection_screen.dart';

class ProjectDashboardScreen extends StatelessWidget {
  final String projectId;

  const ProjectDashboardScreen({super.key, required this.projectId});

  @override
  Widget build(BuildContext context) {
    return ApiCollectionScreen(
      title: 'Project Dashboard',
      route: AppRouter.projects,
      icon: Icons.event_note,
      endpoint: '/projects/$projectId/meetings',
      emptyMessage: 'This project has no meetings yet.',
      itemTitle: (item) => '${item['title'] ?? 'Untitled meeting'}',
      itemSubtitle: (item) => '${item['public_id'] ?? ''}  ${item['status'] ?? ''}',
      itemActions: (context, item) => [
        IconButton(
          tooltip: 'Meeting details',
          onPressed: () => Navigator.pushNamed(context, AppRouter.meetingDetails, arguments: {'id': item['public_id']}),
          icon: const Icon(Icons.chevron_right),
        ),
      ],
    );
  }
}
