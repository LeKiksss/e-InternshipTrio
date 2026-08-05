const admin = require('firebase-admin');
const serviceAccount = require('./serviceAccountKey.json');

if (!admin.apps.length) {
  admin.initializeApp({
    credential: admin.credential.cert(serviceAccount)
  });
}

const db = admin.firestore();

// Lookup table: location string -> coordinates
const locationCoords = {
  'e& Main Building, Al Manakh, Sharjah (25.3547° N, 55.4003° E)': { lat: 25.3547, lng: 55.4003 },
  'e& Store, Al Majaz 3, Sharjah': { lat: 25.3295, lng: 55.3894 },
  'Al Majaz Waterfront, Sharjah': { lat: 25.3320, lng: 55.3838 },
  'Al Qasba, Sharjah': { lat: 25.3387, lng: 55.3838 },
  'University City, Sharjah': { lat: 25.3005, lng: 55.4784 },
  'Mega Mall, Abu Shagara, Sharjah': { lat: 25.3418, lng: 55.3765 },
  'City Centre Sharjah, Al Nahda, Sharjah': { lat: 25.3116, lng: 55.4090 },
  'Dubai Mall, Downtown Dubai': { lat: 25.1972, lng: 55.2796 },
  'Mall of the Emirates, Barsha, Dubai': { lat: 25.1181, lng: 55.2003 },
  'Museum of the Future, Trade Centre, Dubai': { lat: 25.2178, lng: 55.2799 },
  'City Centre Deira, Dubai': { lat: 25.2519, lng: 55.3319 },
  'Yas Mall, Yas Island, Abu Dhabi': { lat: 24.4900, lng: 54.6045 },
  'Corniche Beach, Abu Dhabi': { lat: 24.4686, lng: 54.3232 },
  'Al Ain Mall, Al Kuwaiti, Al Ain': { lat: 24.2075, lng: 55.7447 },
  // Manually-edited outliers you've created by hand:
  'Union Square': { lat: 37.7879, lng: -122.4074 },
};

async function backfillCoordinates() {
  console.log('🔧 Starting coordinate backfill...');
  const snapshot = await db.collection('users').get();

  let updated = 0;
  let skipped = 0;
  const batch = db.batch();

  snapshot.forEach((doc) => {
    const data = doc.data();

    // Skip docs that already have coordinates (don't clobber manual edits)
    if (data.latitude !== undefined && data.longitude !== undefined) {
      skipped++;
      return;
    }

    const coords = locationCoords[data.location];
    if (!coords) {
      console.warn(`⚠️ No coordinate match for location: "${data.location}" (doc ${doc.id})`);
      return;
    }

    batch.update(doc.ref, {
      latitude: coords.lat,
      longitude: coords.lng,
    });
    updated++;
  });

  await batch.commit();
  console.log(`✅ Backfilled ${updated} docs. Skipped ${skipped} (already had coordinates).`);
}

backfillCoordinates().catch(console.error);