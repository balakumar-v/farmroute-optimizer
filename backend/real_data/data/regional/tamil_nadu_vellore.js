  tamil_nadu_vellore: {
    category: "real",
    label: "Tamil Nadu mandis around Vellore, Jan-Feb 2026: tomato & onion",
    about: {"sections": [{"title": "Real", "items": ["7 Tamil Nadu mandis: Katpadi, Vellore, Vaniyampadi, Natrampalli, Tindivanam, Kallakurichi, Ulundurpettai", "Prices and daily arrivals: Agmarknet via India Data Portal, 2026-01-04 to 2026-02-08 (median of days)", "Mandi coordinates: the portal's own"]}, {"title": "Synthetic", "items": ["20 farmers (tomato 16, onion 4) in villages within 18 km of (12.98, 79.20); lots 150-600 kg", "5-vehicle fleet, 12 t = 1.5x the day's 7.9 t of produce", "No public farmer or fleet data exists"]}, {"title": "Assumptions", "items": ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit", "About 60 pickups per round, never more than 30% of a crop's daily absorption by these mandis", "The farm-gate price used in the comparison is assumed"]}, {"title": "Data caveats", "items": ["Only 5 days sampled per mandi, all Sundays (4, 18 and 25 Jan, 1 and 8 Feb): each price is a median of at most 5 days", "Most yards are Uzhavar Sandhai (farmers' markets), so prices look retail-like; only Vellore, Tindivanam and Ulundurpettai are APMC wholesale yards", "Only 28 of 179 Tamil Nadu mandis have coordinates (none in Chennai), so the region is capped at 150 km around Vellore", "Thresholds lowered for this preset: 5 days per series (default 15) and 0.3 t/day (default 1 t)"]}, {"title": "Cleaning", "items": ["0 rows dropped (price or arrival outliers, invalid prices); 0 series with implausible units (e.g. bundle prices) dropped", "131 mandis without coordinates and 0 with suspect ones left out", "35 mandi-crop series absorbing under 0.3 t/day removed (too small for a pickup round)"]}]},
    farmers: [
      { lat: 12.89346, lng: 79.23188, crop: "tomato", qty_kg: 502.3, ready_hr: 0.02, deadline_hr: 7.26 },
      { lat: 12.90194, lng: 79.20613, crop: "tomato", qty_kg: 489.2, ready_hr: 0.23, deadline_hr: 12.91 },
      { lat: 13.03117, lng: 79.02945, crop: "tomato", qty_kg: 581.6, ready_hr: 0.26, deadline_hr: 12.97 },
      { lat: 12.98276, lng: 79.30247, crop: "tomato", qty_kg: 194.2, ready_hr: 0.52, deadline_hr: 9.26 },
      { lat: 12.91851, lng: 79.21998, crop: "tomato", qty_kg: 566.5, ready_hr: 0.9, deadline_hr: 13.74 },
      { lat: 12.9321, lng: 79.22874, crop: "tomato", qty_kg: 350.5, ready_hr: 1.21, deadline_hr: 11.6 },
      { lat: 13.01493, lng: 79.04942, crop: "tomato", qty_kg: 259.7, ready_hr: 1.3, deadline_hr: 11.99 },
      { lat: 13.01036, lng: 79.28381, crop: "tomato", qty_kg: 324.8, ready_hr: 1.39, deadline_hr: 11.54 },
      { lat: 12.98031, lng: 79.11989, crop: "tomato", qty_kg: 156.9, ready_hr: 1.56, deadline_hr: 9.64 },
      { lat: 12.97562, lng: 79.28706, crop: "tomato", qty_kg: 291.8, ready_hr: 1.76, deadline_hr: 13.31 },
      { lat: 12.96266, lng: 79.09913, crop: "onion", qty_kg: 541.6, ready_hr: 1.91, deadline_hr: 14.16 },
      { lat: 12.90048, lng: 79.20774, crop: "tomato", qty_kg: 488.1, ready_hr: 2.2, deadline_hr: 11.15 },
      { lat: 13.04516, lng: 79.04884, crop: "tomato", qty_kg: 523.7, ready_hr: 2.35, deadline_hr: 13.83 },
      { lat: 12.99129, lng: 79.08245, crop: "tomato", qty_kg: 333.5, ready_hr: 2.65, deadline_hr: 10.83 },
      { lat: 12.9556, lng: 79.1037, crop: "onion", qty_kg: 529.8, ready_hr: 3.14, deadline_hr: 9.28 },
      { lat: 12.91211, lng: 79.22087, crop: "tomato", qty_kg: 406.3, ready_hr: 3.37, deadline_hr: 13.07 },
      { lat: 12.9207, lng: 79.23757, crop: "onion", qty_kg: 327.9, ready_hr: 3.57, deadline_hr: 10.16 },
      { lat: 13.03167, lng: 79.04931, crop: "tomato", qty_kg: 463.7, ready_hr: 3.66, deadline_hr: 15.94 },
      { lat: 13.01647, lng: 79.28829, crop: "tomato", qty_kg: 221.3, ready_hr: 3.78, deadline_hr: 13.78 },
      { lat: 12.96337, lng: 79.10685, crop: "onion", qty_kg: 309.2, ready_hr: 3.79, deadline_hr: 11.67 },
    ],
    vehicles: [
      { type_name: "truck_2t", count: 1 },
      { type_name: "reefer_5t", count: 1 },
      { type_name: "reefer_2t", count: 2 },
      { type_name: "reefer_van", count: 1 },
    ],
    markets: [
      { lat: 13.06805, lng: 79.26444, price: { onion: 32.0 }, capacity_kg: { onion: 1700 } }, // Katpadi (Uzhavar Sandhai ) (Vellore), 12 km from farmer centre
      { lat: 12.89844, lng: 79.13112, price: { onion: 27.0, potato: 27.5, tomato: 21.0 }, capacity_kg: { onion: 1300, potato: 650, tomato: 3800 } }, // Vellore (Vellore), 12 km from farmer centre
      { lat: 12.65515, lng: 78.60751, price: { onion: 30.0, potato: 30.0, tomato: 25.0 }, capacity_kg: { onion: 700, potato: 700, tomato: 9080 } }, // Vaniyampadi(Uzhavar Sandhai ) (Tirupathur), 74 km from farmer centre
      { lat: 12.48572, lng: 78.56687, price: { onion: 27.5, potato: 32.5, tomato: 22.5 }, capacity_kg: { onion: 550, potato: 300, tomato: 6180 } }, // Natrampalli(Uzhavar Sandhai ) (Tirupathur), 88 km from farmer centre
      { lat: 12.24492, lng: 79.64416, price: { onion: 27.5, tomato: 20.0 }, capacity_kg: { onion: 900, tomato: 900 } }, // Tindivanam (Viluppuram), 95 km from farmer centre
      { lat: 11.73884, lng: 78.95356, price: { onion: 35.0, tomato: 25.0 }, capacity_kg: { onion: 320, tomato: 830 } }, // Kallakurichi(Uzhavar Sandhai ) (Kallakurichi), 141 km from farmer centre
      { lat: 11.69216, lng: 79.28642, price: { onion: 40.0, tomato: 35.0 }, capacity_kg: { onion: 470, tomato: 420 } }, // Ulundurpettai (Viluppuram), 144 km from farmer centre
    ],
  },
