import 'dart:convert';
import 'package:firebase_ai/firebase_ai.dart';
import 'package:flutter/foundation.dart';

class ChatConstraints {
  final int? minDataGb;
  final int? minMinutes;
  final double? maxBudget;

  ChatConstraints({this.minDataGb, this.minMinutes, this.maxBudget});
}

class ChatConstraintService {
  final GenerativeModel _model = FirebaseAI.googleAI().generativeModel(
    model: 'gemini-flash-latest',
    generationConfig: GenerationConfig(responseMimeType: 'application/json'),
  );

  // Keywords/patterns that indicate an actual plan-change request
  static final RegExp _actionableSignal = RegExp(
    r'\b(gb|gigabyte|data|minute|min|mins|call|calls|voice|'
    r'budget|aed|cost|cheap|cheaper|expensive|price|fee|save|savings|'
    r'plan|upgrade|downgrade|increase|decrease|more|less|unlimited|'
    r'switch|change|need|want|at least|under|below|above|over)\b',
    caseSensitive: false,
  );

  // Also catch bare numbers followed by unit-like words (e.g. "200 mins", "50gb")
  static final RegExp _numericUnitPattern = RegExp(
    r'\d+\s*(gb|mb|min|mins|minute|minutes|aed)',
    caseSensitive: false,
  );

  /// Returns true only if the message plausibly contains a plan request.
  bool isActionableRequest(String message) {
    final trimmed = message.trim();
    if (trimmed.isEmpty) return false;
    return _actionableSignal.hasMatch(trimmed) || _numericUnitPattern.hasMatch(trimmed);
  }

  Future<ChatConstraints> extractConstraints(String userMessage) async {
    final prompt = '''
    Extract telecom plan constraints from this user request. Return ONLY a JSON object, no other text.

    User request: "$userMessage"

    Return JSON with these exact keys (use null if not mentioned):
    - "minDataGb": integer, minimum data in GB the user wants (e.g. "at least 50GB" -> 50)
    - "minMinutes": integer, minimum call minutes the user wants (e.g. "200 or more minutes" -> 200)
    - "maxBudget": number, maximum monthly fee in AED the user wants to pay (e.g. "under 300 AED" -> 300)

    Example output: {"minDataGb": null, "minMinutes": 200, "maxBudget": null}
    ''';

    try {
      final response = await _model.generateContent([Content.text(prompt)]);
      final text = response.text?.trim() ?? '{}';
      final cleaned = text.replaceAll('```json', '').replaceAll('```', '').trim();
      final parsed = jsonDecode(cleaned) as Map<String, dynamic>;

      return ChatConstraints(
        minDataGb: parsed['minDataGb'] != null ? (parsed['minDataGb'] as num).toInt() : null,
        minMinutes: parsed['minMinutes'] != null ? (parsed['minMinutes'] as num).toInt() : null,
        maxBudget: parsed['maxBudget'] != null ? (parsed['maxBudget'] as num).toDouble() : null,
      );
    } catch (e) {
      debugPrint('Constraint extraction error: $e');
      return ChatConstraints();
    }
  }
}