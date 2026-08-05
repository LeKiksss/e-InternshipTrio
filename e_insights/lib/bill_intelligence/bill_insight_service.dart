import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_ai/firebase_ai.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'plan_recommendation_service.dart';

class BillInsightService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;
  final GenerativeModel _model = FirebaseAI.googleAI().generativeModel(
    model: 'gemini-3.5-flash-lite',
  );

  Future<Map<String, dynamic>?> fetchUserData() async {
    final userId = FirebaseAuth.instance.currentUser?.uid ?? 'user_003';
    final doc = await _db.collection('users').doc(userId).get();
    return doc.data();
  }

  Future<String> generateBillInsight({
    required double dataCost,
    required double callsCost,
    required double roamingCost,
    required double addonsCost,
    required double totalBill,
    required double? previousBill,
  }) async {
    String comparisonContext = '';
    if (previousBill != null && previousBill > 0) {
      final diff = (((totalBill - previousBill) / previousBill) * 100).round();
      comparisonContext = diff > 0
          ? 'This bill is $diff% higher than the previous one.'
          : 'This bill is ${diff.abs()}% lower than the previous one.';
    }

    final prompt = '''
    You are an AI assistant inside the e& Insights telecom app.
    Explain this bill in 1-2 short sentences, in plain language.
    Point out which category (data, calls, roaming, or add-ons) is driving the total, and flag it if one category looks unusually high relative to the others.

    Bill Breakdown (AED):
    - Data: $dataCost
    - Calls: $callsCost
    - Roaming: $roamingCost
    - Add-ons: $addonsCost
    - Total: $totalBill
    $comparisonContext

    Rules:
    - Under 30 words.
    - Friendly, clear, no jargon.
    - Do not suggest specific new plans.
    ''';

    try {
      final response = await _model.generateContent([Content.text(prompt)]);
      return response.text?.trim() ?? 'Unable to generate bill insight.';
    } catch (e) {
      debugPrint('Bill Insight Error: $e');
      return 'Unable to generate bill insight right now.';
    }
  }

  Future<String> generatePlanRecommendationInsight(PlanMatch? match, double currentSpend) async {
    if (match == null) {
      return 'Your current plan already fits your projected usage well — no better option needed.';
    }

    final addonNote = match.addonsNotBundled.isNotEmpty
        ? 'Note: ${match.addonsNotBundled.join(", ")} are not included in this plan and must be kept separately.'
        : 'All active add-ons are included in this plan.';

    final bool isSavings = match.estimatedSavings > 0;
    final double absAmount = match.estimatedSavings.abs();

    final costText = isSavings
        ? 'switching saves AED ${absAmount.toStringAsFixed(0)} per month.'
        : 'switching will cost an extra AED ${absAmount.toStringAsFixed(0)} per month, but covers your high projected usage to prevent overages.';

    final prompt = '''
    You are an AI assistant inside the e& Insights telecom app.
    Explain in 2 short sentences why switching to "${match.planName}" (AED ${match.monthlyFee.toStringAsFixed(0)}/mo, ${match.dataLimitGb}GB, ${match.minutesLimit == -1 ? 'unlimited' : match.minutesLimit} mins) is recommended.
    
    Financial Context: $costText
    Add-on Context: $addonNote

    Rules:
    - Maximum 35 words.
    - Friendly, plain language.
    ''';

    try {
      final response = await _model.generateContent([Content.text(prompt)]);
      return response.text?.trim() ?? 'A plan offering better value was found for your usage.';
    } catch (e) {
      debugPrint('Plan Recommendation Insight Error: $e');
      return 'A plan offering better value was found for your usage.';
    }
  }
}