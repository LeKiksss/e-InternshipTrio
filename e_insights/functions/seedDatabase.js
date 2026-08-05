const admin = require('firebase-admin');
const serviceAccount = require('./serviceAccountKey.json');

if (!admin.apps.length) {
  admin.initializeApp({
    credential: admin.credential.cert(serviceAccount)
  });
}

const db = admin.firestore();

// 1. Specific places with real coordinates
const specificLocations = [
  { name: 'e& Main Building, Al Manakh, Sharjah', lat: 25.3547, lng: 55.4003 },
  { name: 'e& Store, Al Majaz 3, Sharjah', lat: 25.3295, lng: 55.3894 },
  { name: 'Al Majaz Waterfront, Sharjah', lat: 25.3320, lng: 55.3838 },
  { name: 'Al Qasba, Sharjah', lat: 25.3387, lng: 55.3838 },
  { name: 'University City, Sharjah', lat: 25.3005, lng: 55.4784 },
  { name: 'Mega Mall, Abu Shagara, Sharjah', lat: 25.3418, lng: 55.3765 },
  { name: 'City Centre Sharjah, Al Nahda, Sharjah', lat: 25.3116, lng: 55.4090 },
  { name: 'Dubai Mall, Downtown Dubai', lat: 25.1972, lng: 55.2796 },
  { name: 'Mall of the Emirates, Barsha, Dubai', lat: 25.1181, lng: 55.2003 },
  { name: 'Museum of the Future, Trade Centre, Dubai', lat: 25.2178, lng: 55.2799 },
  { name: 'City Centre Deira, Dubai', lat: 25.2519, lng: 55.3319 },
  { name: 'Yas Mall, Yas Island, Abu Dhabi', lat: 24.4900, lng: 54.6045 },
  { name: 'Corniche Beach, Abu Dhabi', lat: 24.4686, lng: 54.3232 },
  { name: 'Al Ain Mall, Al Kuwaiti, Al Ain', lat: 24.2075, lng: 55.7447 },
  {name: 'Union Square', lat: 37.7872, lng: -122.4081}
];

function jitterCoord(value) {
  return value + (Math.random() - 0.5) * 0.01; // ~1km spread
}

// 2. Plan tiers
const planTiers = [
  'Starter', 'Freedom', 'Freedom Unlimited', 'e& Family', 'e& Business',
  'Emirates Freedom', 'VIP Platinum', '5G Ultra Speed', 'Student Pass', 'Flexi Prepaid'
];

const dataAllowances = [10, 20, 50, 100, 200, 300, 500, 1000]; // GB

const minuteTiers = [100, 300, 500, 1000, -1]; // -1 = unlimited

const addonBundlePool = [
  [],
  ['Social Pass Unlimited'],
  ['Gaming Booster (Ping Optimizer)'],
  ['Social Pass Unlimited', 'Gaming Booster (Ping Optimizer)'],
  ['Social Pass Unlimited', 'International Calling 100 Mins'],
  ['Gaming Booster (Ping Optimizer)', 'OTT Video Streaming Pass (Netflix/Amazon Prime)'],
];

const addonBaseCost = {
  'Social Pass Unlimited': 25,
  'Gaming Booster (Ping Optimizer)': 30,
  'International Calling 100 Mins': 40,
  'OTT Video Streaming Pass (Netflix/Amazon Prime)': 45,
  'Roaming Pass Unlimited': 50,
  'Music Streaming Add-on (Anghami/Spotify)': 20,
  'e& CyberSecurity Shield': 15,
  'Cloud Backup 1TB': 35,
  'Speed Boost Turbo 1Gbps': 60,
  'E-Sports Ultra Low Latency Pass': 40,
};

const plans = [];
let planIdCounter = 1;

for (const tier of planTiers) {
  for (const gb of dataAllowances) {
    const minutes = minuteTiers[planIdCounter % minuteTiers.length];
    const includedAddons = addonBundlePool[planIdCounter % addonBundlePool.length];

    const bundledAddonValue = includedAddons.reduce((sum, name) => sum + (addonBaseCost[name] || 0), 0);
    const minutesCost = minutes === -1 ? 60 : minutes * 0.08;
    const price = Math.round(gb * 2 + minutesCost + (bundledAddonValue * 0.6) + (tier.length * 3));

    plans.push({
      planId: `PLAN_${planIdCounter.toString().padStart(3, '0')}`,
      planName: `${tier} ${gb >= 1000 ? '1TB' : gb + 'GB'}`,
      monthlyFee: price,
      dataLimitGb: gb,
      minutesLimit: minutes,
      includedAddons: includedAddons,
    });
    planIdCounter++;
  }
}

for (let i = 1; i <= 20; i++) {
  const minutes = minuteTiers[i % minuteTiers.length];
  const includedAddons = addonBundlePool[(i + 2) % addonBundlePool.length];
  plans.push({
    planId: `PLAN_${planIdCounter.toString().padStart(3, '0')}`,
    planName: `e& Custom VIP Elite ${i * 50}GB`,
    monthlyFee: 280 + (i * 22),
    dataLimitGb: i * 50,
    minutesLimit: -1,
    includedAddons: includedAddons.length ? includedAddons : ['Social Pass Unlimited'],
  });
  planIdCounter++;
}

// 3. Add-ons pool (for random assignment to users)
const availableAddons = [
  { name: 'Roaming Pass Unlimited', cost: '50 AED' },
  { name: 'Gaming Booster (Ping Optimizer)', cost: '30 AED' },
  { name: 'International Calling 100 Mins', cost: '40 AED' },
  { name: 'Social Pass Unlimited', cost: '25 AED' },
  { name: 'Music Streaming Add-on (Anghami/Spotify)', cost: '20 AED' },
  { name: 'OTT Video Streaming Pass (Netflix/Amazon Prime)', cost: '45 AED' },
  { name: 'e& CyberSecurity Shield', cost: '15 AED' },
  { name: 'Cloud Backup 1TB', cost: '35 AED' },
  { name: 'Speed Boost Turbo 1Gbps', cost: '60 AED' },
  { name: 'E-Sports Ultra Low Latency Pass', cost: '40 AED' }
];

// 4. Customer names
const names = [
  'Hamzah Riyaz',
  'Ahmed Mansoor', 'Fatima Al Zahra', 'Zaid Khan', 'Sarah Jenkins', 'Omar Al Hashimi',
  'Tariq Malik', 'Elena Rostova', 'Rohan Verma', 'Laila Saeed', 'Marcus Vance',
  'Yasmin Noor', 'Hamdan Al Maktoum', 'Chloe Bennett', 'Vikram Patel', 'Mariam Al Qassimi',
  'Siddharth Nair', 'Aisha Farooq', 'Carlos Mendez', 'Hana Abdullah', 'David Miller',
  'Noura Al Suwaidi', 'Karan Sharma', 'Sofia Rossi', 'Youssef Khalil', 'Grace Taylor',
  'Sultan Al Nuaimi', 'Ananya Roy', 'Johnathan Doe', 'Reem Al Falasi', 'Khalid Rahmani',
  'Priya Sundaram', 'Alexander Petrov', 'Maya Lin', 'Ibrahim Al Ali', 'Rachel Green',
  'Bilal Chishti', 'Nadia Al Shamsi', 'George Clark', 'Sana Mir', 'Mustafa Al Sayed',
  'Meera Kapoor', 'Daniel Craig', 'Layla Mubarak', 'Arjun Kapoor', 'Zahra Hussain',
  'Oliver Smith', 'Salama Al Mansoori', 'Rami Haddad', 'Deepak Joshi'
];

async function seed50UsersAnd100Plans() {
  console.log(' Starting database seeding...');
  const batch = db.batch();

  console.log(`Uploading ${plans.length} available plans...`);
  plans.forEach((plan) => {
    const planRef = db.collection('plans').doc(plan.planId);
    batch.set(planRef, plan);
  });

  for (let i = 1; i <= 50; i++) {
    const userId = `user_${i.toString().padStart(3, '0')}`;
    const name = names[i - 1];

    const locationObj = (name === 'Hamzah Riyaz')
      ? specificLocations[0]
      : specificLocations[Math.floor(Math.random() * specificLocations.length)];

    const selectedPlan = plans[Math.floor(Math.random() * plans.length)];
    const dataUsedGb = Math.floor(Math.random() * (selectedPlan.dataLimitGb * 0.9));

    const minutesUsed = selectedPlan.minutesLimit === -1
      ? Math.floor(Math.random() * 1200)
      : Math.floor(Math.random() * (selectedPlan.minutesLimit * 0.9));

    const addonCount = Math.floor(Math.random() * 4) + 1;
    const shuffledAddons = [...availableAddons].sort(() => 0.5 - Math.random());
    const activeAddons = shuffledAddons.slice(0, addonCount).map((addon) => ({
      ...addon,
      used: Math.random() > 0.4
    }));

    const downloadMbps = Math.floor(Math.random() * 850) + 100;
    const uploadMbps = Math.floor(downloadMbps * (Math.random() * 0.3 + 0.1));

    const userRef = db.collection('users').doc(userId);

    batch.set(userRef, {
      userId,
      name,
      email: `${name.toLowerCase().replace(/ /g, '.')}@example.com`,
      location: locationObj.name,
      latitude: jitterCoord(locationObj.lat),
      longitude: jitterCoord(locationObj.lng),
      planName: selectedPlan.planName,
      monthlyFee: selectedPlan.monthlyFee,
      dataLimitGb: selectedPlan.dataLimitGb,
      dataUsedGb: dataUsedGb,
      minutesLimit: selectedPlan.minutesLimit,
      minutesUsed: minutesUsed,
      activeAddons: activeAddons,
      lastSpeedTest: {
        downloadMbps: downloadMbps,
        uploadMbps: uploadMbps,
        timestamp: admin.firestore.FieldValue.serverTimestamp(),
        locationTested: locationObj.name
      },
      createdAt: admin.firestore.FieldValue.serverTimestamp()
    });
  }

  await batch.commit();
  console.log(`Successfully uploaded ${plans.length} plans to 'plans' collection!`);
  console.log('Successfully seeded 50 user profiles (including Hamzah Riyaz) to "users" collection!');
}

seed50UsersAnd100Plans().catch(console.error);