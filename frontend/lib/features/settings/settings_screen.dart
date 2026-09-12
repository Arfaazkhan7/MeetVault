import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Settings',
      currentRoute: AppRouter.settings,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: const [
          Card(
            child: SwitchListTile(
              value: true,
              onChanged: null,
              title: Text('System theme'),
              subtitle: Text('Uses device theme'),
            ),
          ),
          Card(
            child: ListTile(
              leading: Icon(Icons.storage_outlined),
              title: Text('API base URL'),
              subtitle: Text(ApiService.baseUrl),
            ),
          ),
        ],
      ),
    );
  }
}
