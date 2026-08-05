const functions = require('firebase-functions');
const admin = require('firebase-admin');
const { GoogleGenerativeAI } = require('@google/generative-ai');

admin.initializeApp();
const db = admin.firestore();

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

// Helper function to query local users and calculate area speed metrics
async function calculateRegionalMetrics(userLocation, currentDownload) {
  if (!userLocation) return null;

  try {
    const snapshot = await db
      .collection('users')
      .where('location', '==', userLocation)
      .get();

    if (snapshot.empty) return null;

    let totalDownload = 0;
    let count = 0;
    let slowerUserCount = 0;

    snapshot.forEach((doc) => {
      const data = doc.data();
      if (data.lastSpeedTest && data.lastSpeedTest.downloadMbps) {
        const speed = data.lastSpeedTest.downloadMbps;
        totalDownload += speed;
        count++;
        if (currentDownload > speed) {
          slowerUserCount++;
        }
      }
    });

    if (count === 0) return null;

    const avgDownload = Math.round(totalDownload / count);
    const percentile = count > 1 ? Math.round((slowerUserCount / (count - 1)) * 100) : 100;
    const diffPercentage = Math.round(((currentDownload - avgDownload) / avgDownload) * 100);

    return {
      avgDownload,
      percentile,
      diffPercentage,
      totalUsersInArea: count
    };
  } catch (error) {
    console.error('Regional calculation error:', error);
    return null;
  }
}

// 1. SPEED INSIGHT: Everyday activities + Area Comparison
exports.generateSpeedInsight = functions.https.onCall(async (data, context) => {
  const { downloadMbps, uploadMbps, location } = data;

  try {
    // Perform deterministic Firestore query for area comparison
    const regionalData = await calculateRegionalMetrics(location, downloadMbps);

    const model = genAI.getGenerativeModel({ model: 'gemini-1.5-flash' });

    let areaContext = '';
    if (regionalData) {
      const comparisonText = regionalData.diffPercentage >= 0 
        ? `${regionalData.diffPercentage}% faster than average` 
        : `${Math.abs(regionalData.diffPercentage)}% slower than average`;

      areaContext = `
      Area Comparison Data:
      - User Location: ${location}
      - Area Average Download: ${regionalData.avgDownload} Mbps
      - Performance vs Area: ${comparisonText} (Faster than ${regionalData.percentile}% of local users).
      `;
    }

    const prompt = `
    You are an AI assistant inside the e& Insights telecom app.
    Provide a 2-sentence speed assessment:
    Sentence 1: Summarize everyday activities this network speed supports (e.g. 4K streaming, multiplayer gaming, video calls).
    Sentence 2: ${regionalData ? 'Compare their speed to the local area average using the provided area data.' : 'Encourage them on their current network health.'}

    Speed Data:
    - Download: ${downloadMbps} Mbps
    - Upload: ${uploadMbps} Mbps
    ${areaContext}

    Rules:
    - Keep total response under 35 words.
    - Friendly, professional, and crisp tone.
    - DO NOT mention bill details or data limits.
    `;

    const result = await model.generateContent(prompt);
    
    return { 
      success: true, 
      insight: result.response.text().trim(),
      regionalStats: regionalData // Sent back to Flutter UI for display cards or maps
    };
  } catch (error) {
    console.error('Speed Insight Error:', error);
    return { success: false, error: error.message };
  }
});

// 2. BILL INTELLIGENCE: Plan usage, wasted add-ons & smart plan recommendation
exports.generateBillIntelligence = functions.https.onCall(async (data, context) => {
    const { userId } = data;
  
    try {
      // A. Fetch user document from Firestore
      let userData = {};
      if (userId) {
        const userDoc = await db.collection('users').doc(userId).get();
        userData = userDoc.data() || {};
      }
  
      const currentPlanName = userData.planName ?? 'Freedom Unlimited 325';
      const currentFee = userData.monthlyFee ?? '325 AED';
      const dataLimitGb = userData.dataLimitGb ?? 100;
      const dataUsedGb = userData.dataUsedGb ?? 38;
      const activeAddons = userData.activeAddons ?? [
        { name: 'Roaming Pass', cost: '50 AED', used: false },
        { name: 'Gaming Booster', cost: '30 AED', used: true },
      ];
  
      // B. Fetch available plans from 'plans' collection to find better options
      const plansSnapshot = await db.collection('plans').get();
      const allPlans = [];
      plansSnapshot.forEach((doc) => allPlans.push(doc.data()));
  
      // Filter plans that comfortably cover the user's actual data usage
      const suitablePlans = allPlans
        .filter((p) => p.dataLimitGb >= dataUsedGb)
        .slice(0, 15); // Limit to top 15 matches to keep prompt compact
  
      // C. Initialize Gemini with Native JSON output
      const model = genAI.getGenerativeModel({ 
        model: 'gemini-1.5-flash',
        generationConfig: {
          responseMimeType: 'application/json'
        }
      });
  
      const prompt = `
      You are a smart telecom financial advisor for e& Insights.
      Analyze the user's monthly bill and recommend a better plan from the available list if applicable.
  
      User Account Details:
      - Current Plan: ${currentPlanName} (${currentFee})
      - Data Usage: Used ${dataUsedGb} GB out of ${dataLimitGb} GB allowance.
      - Active Add-ons: ${JSON.stringify(activeAddons)}
  
      Available Alternative Plans:
      ${JSON.stringify(suitablePlans)}
  
      Rules for Recommendation:
      1. If the user uses far less data than their current plan limit, suggest a cheaper plan from the list that still covers their usage (Downgrade/Save Money).
      2. If they are close to hitting their data limit, suggest a better value plan (Upgrade/Avoid Overage).
      3. If their current plan is already optimal, recommend staying on it.
  
      Provide a JSON object containing:
      - "usageSummary": A concise overview of plan utilization.
      - "wastedAddons": An array of unused add-ons or wasted cost items.
      - "recommendedPlan": {
          "planName": "Exact name of recommended plan",
          "monthlyFee": "Exact fee of recommended plan",
          "savingsOrBenefit": "e.g., Saves 75 AED/mo or Gives 50GB extra data"
        },
      - "recommendation": 1 actionable advice sentence explaining why this plan fits them best.
      `;
  
      const result = await model.generateContent(prompt);
      const parsedData = JSON.parse(result.response.text());
      
      return { success: true, analysis: parsedData };
    } catch (error) {
      console.error('Bill Intelligence Error:', error);
      return { success: false, error: error.message };
    }
  });
exports.runSeeder = functions.https.onRequest(async (req, res) => {
    try {
      // Requires and executes seedDatabase.js inside the function execution context
      require('./seedDatabase');
      res.send('✅ Database seeding process started! Check your Firebase Functions logs.');
    } catch (error) {
      console.error('Seeder Error:', error);
      res.status(500).send('Error seeding database: ' + error.message);
    }
  });