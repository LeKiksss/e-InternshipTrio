import 'package:e_insights/linear_tracker.dart';
import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'bill_insight_service.dart';
import 'plan_recommendation_service.dart';
import 'chat_constraint_service.dart';

class BillScreen extends StatefulWidget {
  const BillScreen({super.key});

  @override
  State<BillScreen> createState() => _BillScreenState();
}

class _BillScreenState extends State<BillScreen> {
  final BillInsightService _billService = BillInsightService();
  final PlanRecommendationService _planService = PlanRecommendationService();
  final ChatConstraintService _chatService = ChatConstraintService();
  final TextEditingController _chatController = TextEditingController();

  bool _isLoading = true;
  double _dataCost = 0;
  double _callsCost = 0;
  double _roamingCost = 0;
  double _addonsCost = 0;
  double _totalBill = 0;
  final lastDayOfMonth = DateTime(DateTime.now().year, DateTime.now().month + 1, 0);
  String get _dueDate => "${lastDayOfMonth.day.toString()}-${lastDayOfMonth.month.toString().padLeft(2, '0')}-${lastDayOfMonth.year.toString().padLeft(2, '0')}";
  String _aiInsight = '';
  bool _hasAnomaly = false;

  // Stored so chat re-queries can reuse the user's actual usage data
  int _dataUsedGb = 0;
  int _minutesUsed = 0;
  int _minutesLimit = 0;
  int _dataLimit = 0;

  double _monthlyFee = 0;
  List<Map<String, dynamic>> _activeAddonsList = [];

  PlanMatch? _recommendedPlan;
  String _planInsight = '';
  bool _loadingPlanInsight = true;

  final List<Map<String, String>> _chatMessages = []; // {'sender': 'user'/'ai', 'text': ...}
  bool _isChatLoading = false;

  @override
  void initState() {
    super.initState();
    _loadBillData();
  }

  Future<void> _loadBillData() async {
    setState(() => _isLoading = true);

    final data = await _billService.fetchUserData();

    if (data != null) {
      final monthlyFee = (data['monthlyFee'] as num).toDouble();
      final addons = (data['activeAddons'] as List<dynamic>? ?? []);
      _dataUsedGb = data['dataUsedGb'];
      _minutesUsed = data['minutesUsed'];
      _minutesLimit= data['minutesLimit'];
      _dataLimit = data['dataLimitGb'];



      double addonsCost = 0;
      for (final addon in addons) {
        final costStr = addon['cost'] as String? ?? '0 AED';
        addonsCost += double.tryParse(costStr.replaceAll(RegExp(r'[^0-9.]'), '')) ?? 0;
      }

      final dataCost = monthlyFee * 0.5;
      final callsCost = monthlyFee * 0.25;
      final roamingCost = monthlyFee * 0.25;
      final totalBill = dataCost + callsCost + roamingCost + addonsCost;

      

      final insight = await _billService.generateBillInsight(
        dataCost: dataCost,
        callsCost: callsCost,
        roamingCost: roamingCost,
        addonsCost: addonsCost,
        totalBill: totalBill,
        previousBill: totalBill * 0.78,
      );
      _monthlyFee = monthlyFee;
      _activeAddonsList = List<Map<String, dynamic>>.from(addons);

      if (mounted) {
        setState(() {
          _dataCost = dataCost;
          _callsCost = callsCost;
          _roamingCost = roamingCost;
          _addonsCost = addonsCost;
          _totalBill = totalBill;
          _dueDate ;
          _aiInsight = insight;
          _hasAnomaly = roamingCost > (totalBill * 0.25);
          _isLoading = false;
        });
      }

      final match = await _planService.findBetterPlan(
        dataUsedGb: _dataUsedGb,
        minutesUsed: _minutesUsed,
        currentMonthlyFee: _monthlyFee,
        currentDataLimitGb: _dataLimit,
        currentMinutesLimit: _minutesLimit,
        activeAddons: _activeAddonsList,
      );

      final planInsight = await _billService.generatePlanRecommendationInsight(match, monthlyFee + addonsCost);

      if (mounted) {
        setState(() {
          _recommendedPlan = match;
          _planInsight = planInsight;
          _loadingPlanInsight = false;
        });
      }
    } else {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _sendChatMessage() async {
  final message = _chatController.text.trim();
  if (message.isEmpty) return;

  setState(() {
    _chatMessages.add({'sender': 'user', 'text': message});
  });
  _chatController.clear();

  // Gate: only call the AI if the message actually looks like a plan request
  if (!_chatService.isActionableRequest(message)) {
    setState(() {
      _chatMessages.add({
        'sender': 'ai',
        'text': 'I can help you find a better plan — try telling me things like "I need at least 200 minutes" or "keep it under 300 AED".',
      });
    });
    return; // no API call made
  }

  setState(() => _isChatLoading = true);

  final constraints = await _chatService.extractConstraints(message);

  final match = await _planService.findBetterPlan(
    dataUsedGb: _dataUsedGb,
    minutesUsed: _minutesUsed,
    currentMonthlyFee: _monthlyFee,
    activeAddons: _activeAddonsList,
    minDataGbOverride: constraints.minDataGb,
    minMinutesOverride: constraints.minMinutes,
    maxBudget: constraints.maxBudget,
    currentDataLimitGb: _dataLimit,
    currentMinutesLimit: _minutesLimit
  );

  final planInsight = await _billService.generatePlanRecommendationInsight(match, _monthlyFee + _addonsCost);

  if (mounted) {
    setState(() {
      _recommendedPlan = match;
      _planInsight = planInsight;
      _chatMessages.add({
        'sender': 'ai',
        'text': match != null
            ? 'Updated recommendation: ${match.planName} — $planInsight'
            : 'No plan matches that requirement. Try adjusting it.',
      });
      _isChatLoading = false;
    });
  }
}

  BoxDecoration get _cardDecoration => BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(color: Colors.black.withOpacity(0.06), blurRadius: 12, offset: const Offset(0, 4)),
        ],
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F5F7),
      body: SafeArea(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : SingleChildScrollView(
                padding: const EdgeInsets.all(15),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 20),
                    _buildHeader(),
                    const SizedBox(height: 20),
                    _buildLatestBillCard(),
                    const SizedBox(height: 15),
                    _buildBillAnalysisCard(),
                    const SizedBox(height: 15),
                    _buildCategoryGrid(),
                    const SizedBox(height: 15),
                    LinearTracker(current: _dataUsedGb,total:_dataLimit,label: "Data Usage",type: "GB",),
                    const SizedBox(height: 15),
                    LinearTracker(current: _minutesUsed,total:_minutesLimit,label: "Minutes Usage",type: "Mins",),
                    const SizedBox(height: 15),
                    if (_hasAnomaly) _buildAnomalyCard(),
                    const SizedBox(height: 15),
                    _buildPlanRecommendationCard(),
                    const SizedBox(height: 15),
                    _buildChatCard(),
                  ],
                ),
              ),
      ),
    );
  }

  Widget _buildHeader() {
    return Row(
      children: [
        Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            color: const Color.fromARGB(255, 249, 213, 213),
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Icon(Icons.receipt_long_rounded, color: Color.fromARGB(255, 255, 71, 71)),
        ),
        const SizedBox(width: 20),
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('BILL INTELLIGENCE',
                  style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 12)),
              Text('Understand every charge',
                  style: TextStyle(fontWeight: FontWeight.bold, color: Colors.black, fontSize: 17)),
              Text('Review your bill, spot unusual charges, and compare plan options.',
                  style: TextStyle(fontWeight: FontWeight.w400, color: Colors.grey, fontSize: 12)),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildLatestBillCard() {
    return Container(
      width: double.infinity,
      decoration: _cardDecoration,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('LATEST BILL',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.8)),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Amount due', style: TextStyle(fontSize: 13, color: Colors.grey)),
                    Text('AED ${_totalBill.toStringAsFixed(0)}',
                        style: const TextStyle(fontSize: 30, fontWeight: FontWeight.bold, color: Colors.black)),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(color: const Color(0xFFFFF3E0), borderRadius: BorderRadius.circular(10)),
                child: Text('Due $_dueDate',
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFFF57C00))),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(_aiInsight, style: TextStyle(fontSize: 14, color: Colors.grey.shade700, height: 1.4)),
        ],
      ),
    );
  }

  Widget _buildBillAnalysisCard() {
    return Container(
      width: double.infinity,
      decoration: _cardDecoration,
      padding: const EdgeInsets.all(16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('BILL ANALYSIS',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.8)),
                const SizedBox(height: 8),
                Text('AED ${_totalBill.toStringAsFixed(0)}',
                    style: const TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text('Due $_dueDate', style: TextStyle(fontSize: 13, color: Colors.grey.shade600)),
              ],
            ),
          ),
          SizedBox(
            width: 110,
            height: 110,
            child: Stack(
              alignment: Alignment.center,
              children: [
                PieChart(
                  PieChartData(
                    sections: [
                      PieChartSectionData(value: _dataCost, color: const Color(0xFFD32F2F), showTitle: false, radius: 16),
                      PieChartSectionData(value: _roamingCost, color: const Color(0xFF7C4DFF), showTitle: false, radius: 16),
                      PieChartSectionData(value: _addonsCost, color: const Color(0xFF448AFF), showTitle: false, radius: 16),
                      PieChartSectionData(value: _callsCost, color: const Color(0xFFF57C00), showTitle: false, radius: 16),
                    ],
                    centerSpaceRadius: 38,
                    sectionsSpace: 2,
                  ),
                ),
                const Text('100%', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCategoryGrid() {
    return Column(
      children: [
        Row(
          children: [
            Expanded(child: _categoryTile('Data', _dataCost, const Color(0xFFD32F2F))),
            const SizedBox(width: 12),
            Expanded(child: _categoryTile('Calls', _callsCost, const Color(0xFFF57C00))),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(child: _categoryTile('Roaming', _roamingCost, const Color(0xFF7C4DFF))),
            const SizedBox(width: 12),
            Expanded(child: _categoryTile('Add-ons', _addonsCost, const Color(0xFF448AFF))),
          ],
        ),
      ],
    );
  }

  Widget _categoryTile(String label, double amount, Color color) {
    return Container(
      decoration: _cardDecoration,
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
              const SizedBox(width: 6),
              Text(label, style: TextStyle(fontSize: 13, color: Colors.grey.shade600)),
            ],
          ),
          const SizedBox(height: 6),
          Text('AED ${amount.toStringAsFixed(0)}',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  Widget _buildAnomalyCard() {
    return Container(
      width: double.infinity,
      decoration: _cardDecoration,
      padding: const EdgeInsets.all(16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(color: const Color(0xFFFFF3E0), borderRadius: BorderRadius.circular(12)),
            child: const Icon(Icons.warning_amber_rounded, color: Color(0xFFF57C00)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('ANOMALY DETECTED',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.8)),
                const SizedBox(height: 4),
                const Text('Your roaming charges look unusually high this month.',
                    style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text('Most of the increase came from roaming charges.',
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade600)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPlanRecommendationCard() {
    return Container(
      width: double.infinity,
      decoration: _cardDecoration,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('PLAN RECOMMENDATION',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.8)),
          const SizedBox(height: 10),
          if (_loadingPlanInsight)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2)),
            )
          else ...[
            if (_recommendedPlan != null) ...[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(_recommendedPlan!.planName,
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(color: const Color(0xFFE8F5E9), borderRadius: BorderRadius.circular(10)),
                    child: Text(
                      _recommendedPlan!.estimatedSavings > 0
                          ? 'Save AED ${_recommendedPlan!.estimatedSavings.toStringAsFixed(0)}/mo'
                          : 'Match found',
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF388E3C)),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                '${_recommendedPlan!.dataLimitGb}GB · ${_recommendedPlan!.minutesLimit == -1 ? "Unlimited mins" : "${_recommendedPlan!.minutesLimit} mins"} · AED ${_recommendedPlan!.monthlyFee.toStringAsFixed(0)}/mo',
                style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
              ),
              const SizedBox(height: 10),
            ],
            Text(_planInsight, style: TextStyle(fontSize: 14, color: Colors.grey.shade700, height: 1.4)),
          ],
        ],
      ),
    );
  }

  Widget _buildChatCard() {
    return Container(
      width: double.infinity,
      decoration: _cardDecoration,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('ASK FOR A DIFFERENT PLAN',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey, letterSpacing: 0.8)),
          const SizedBox(height: 4),
          Text('e.g. "I need at least 200 minutes" or "keep it under 300 AED"',
              style: TextStyle(fontSize: 12, color: Colors.grey.shade500)),
          const SizedBox(height: 12),
          if (_chatMessages.isNotEmpty)
            Column(
              children: _chatMessages.map((msg) {
                final isUser = msg['sender'] == 'user';
                return Align(
                  alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.7),
                    decoration: BoxDecoration(
                      color: isUser ? const Color(0xFFD32F2F) : Colors.grey.shade100,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      msg['text'] ?? '',
                      style: TextStyle(color: isUser ? Colors.white : Colors.black87, fontSize: 13),
                    ),
                  ),
                );
              }).toList(),
            ),
          if (_isChatLoading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _chatController,
                  decoration: InputDecoration(
                    hintText: 'Type your requirement...',
                    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide(color: Colors.grey.shade300),
                    ),
                  ),
                  onSubmitted: (_) => _sendChatMessage(),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                onPressed: _isChatLoading ? null : _sendChatMessage,
                icon: const Icon(Icons.send_rounded, color: Color(0xFFD32F2F)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}