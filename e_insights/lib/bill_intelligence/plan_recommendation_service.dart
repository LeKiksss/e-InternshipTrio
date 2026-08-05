import 'package:cloud_firestore/cloud_firestore.dart';

class PlanMatch {
  final String planId;
  final String planName;
  final double monthlyFee;
  final int dataLimitGb;
  final int minutesLimit;
  final List<String> includedAddons;
  final double estimatedSavings; // Positive = money saved, Negative = net extra cost
  final List<String> addonsNotBundled;
  final bool isUpgrade; // True if this plan is needed to avoid an overage

  PlanMatch({
    required this.planId,
    required this.planName,
    required this.monthlyFee,
    required this.dataLimitGb,
    required this.minutesLimit,
    required this.includedAddons,
    required this.estimatedSavings,
    required this.addonsNotBundled,
    required this.isUpgrade,
  });
}

class PlanRecommendationService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;

  double projectMonthEnd(num usedSoFar, {double variabilityFactor = 0.85}) {
    final now = DateTime.now();
    final daysElapsed = now.day;
    final daysInMonth = DateTime(now.year, now.month + 1, 0).day;
    
    if (daysElapsed == 0) return usedSoFar.toDouble();

    final dailyRate = usedSoFar / daysElapsed;
    final remainingDays = daysInMonth - daysElapsed;
    final adjustedProjectedRemaining = remainingDays * dailyRate * variabilityFactor;

    return usedSoFar + adjustedProjectedRemaining;
  }

  Future<PlanMatch?> findBetterPlan({
    required int dataUsedGb,
    required int currentDataLimitGb,
    required int minutesUsed,
    required int currentMinutesLimit,
    required double currentMonthlyFee, // Base plan fee (EXCLUDING add-ons)
    required List<Map<String, dynamic>> activeAddons,
    int? minDataGbOverride,
    int? minMinutesOverride,
    double? maxBudget,
  }) async {
    final projectedDataGb = projectMonthEnd(dataUsedGb);
    final projectedMinutes = projectMonthEnd(minutesUsed);

    final needsDataUpgrade = projectedDataGb > currentDataLimitGb;
    final needsMinutesUpgrade = currentMinutesLimit != -1 && projectedMinutes > currentMinutesLimit;
    final needsUpgrade = needsDataUpgrade || needsMinutesUpgrade;

    final requiredDataGb = projectedDataGb > (minDataGbOverride ?? 0)
        ? projectedDataGb
        : (minDataGbOverride ?? 0).toDouble();
        
    final requiredMinutes = projectedMinutes > (minMinutesOverride ?? 0)
        ? projectedMinutes
        : (minMinutesOverride ?? 0).toDouble();

    // 1. Calculate actual current add-on spend
    double currentAddonSpend = 0;
    for (final addon in activeAddons) {
      final costStr = (addon['cost'] as String? ?? '0 AED');
      currentAddonSpend += double.tryParse(costStr.replaceAll(RegExp(r'[^0-9.]'), '')) ?? 0;
    }
    
    // Ensure currentTotalSpend is Base Plan + Add-ons
    final currentTotalSpend = currentMonthlyFee + currentAddonSpend;

    final snapshot = await _db.collection('plans').get();
    final candidates = <PlanMatch>[];

    for (final doc in snapshot.docs) {
      final data = doc.data();
      final dataLimitGb = (data['dataLimitGb'] as num).toInt();
      final minutesLimit = (data['minutesLimit'] as num).toInt();
      final fee = (data['monthlyFee'] as num).toDouble();
      final includedAddons = List<String>.from(data['includedAddons'] ?? []);

      final coversData = dataLimitGb >= requiredDataGb;
      final coversMinutes = minutesLimit == -1 || minutesLimit >= requiredMinutes;
      if (!coversData || !coversMinutes) continue;
      if (maxBudget != null && fee > maxBudget) continue;

      // 2. Determine unbundled add-on costs for this candidate plan
      final candidateIncludedSet = includedAddons.toSet();
      final addonsNotBundled = <String>[];
      double unbundledAddonsCost = 0;

      for (final addon in activeAddons) {
        final addonName = addon['name'] as String? ?? '';
        if (!candidateIncludedSet.contains(addonName)) {
          addonsNotBundled.add(addonName);
          final costStr = (addon['cost'] as String? ?? '0 AED');
          unbundledAddonsCost += double.tryParse(costStr.replaceAll(RegExp(r'[^0-9.]'), '')) ?? 0;
        }
      }

      final newTotalSpend = fee + unbundledAddonsCost;
      final savings = currentTotalSpend - newTotalSpend;

      final qualifies = savings > 0 || needsUpgrade || minDataGbOverride != null || minMinutesOverride != null || maxBudget != null;

      if (qualifies) {
        candidates.add(PlanMatch(
          planId: data['planId'] ?? doc.id,
          planName: data['planName'] ?? 'Unknown Plan',
          monthlyFee: fee,
          dataLimitGb: dataLimitGb,
          minutesLimit: minutesLimit,
          includedAddons: includedAddons,
          estimatedSavings: savings,
          addonsNotBundled: addonsNotBundled,
          isUpgrade: needsUpgrade && savings <= 0,
        ));
      }
    }

    if (candidates.isEmpty) return null;

    if (needsUpgrade || minDataGbOverride != null || minMinutesOverride != null || maxBudget != null) {
      candidates.sort((a, b) => a.monthlyFee.compareTo(b.monthlyFee));
    } else {
      candidates.sort((a, b) => b.estimatedSavings.compareTo(a.estimatedSavings));
    }

    return candidates.first;
  }
}