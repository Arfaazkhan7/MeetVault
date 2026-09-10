import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class AdminScreen extends StatelessWidget {
  const AdminScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Admin',
      currentRoute: AppRouter.admin,
      child: const UiState.empty('Admin controls require backend administration APIs.'),
    );
  }
}
