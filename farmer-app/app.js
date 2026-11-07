"use strict";
// Farmroute farmer app: no build step. Talks to the backend's /farmer/login, /farmer/me, /farmer/phone and
// /farmer/chat + /farmer/requests (asking the FPO for a change) routes only.
const API = (window.FARMER_API || "").replace(/\/$/, ""), STALE_H = 24, $ = s => document.querySelector(s);
const L = { en: {
 login:"Log in",id:"Farmer ID",pin:"PIN",help:"Use the farmer ID and PIN from your FPO.",wrong:"Wrong farmer ID or PIN.",comes:"The truck is coming at",takes:"It takes your {kg} kg of {crop} to Mandi {m}.",changed:"Something changed for you since the last plan.",recv:"You receive about",est:"Estimate",listen:"Listen to everything",offer:"Check a trader's offer",day:"Your day",s1:"{t} Truck comes to your farm",s1b:"Have your produce ready.",s2:"Sold at Mandi {m}",s2b:"You do not need to go.",map:"Open on the map",s3:"Payment: about {v}",s3b:"Paid by your FPO after the sale.",how:"How this is worked out",upd:"Updated {t}. Works offline.",offl:"No signal. This is your card from {t}.",old:"This card is more than a day old. Do not rely on it.",maybe:"The plan may have changed since then. Check again when you have signal.",back:"Back",howT:"How your {v} is worked out",exact:"Exact",derived:"Derived",assumed:"Assumed",dExact:"You or your FPO entered this.",dDer:"Worked out from your numbers and the trip.",dAss:"A guess of what a trader would pay at your door. A real offer can differ.",doorsI:"Doorstep value",share:"Your share of the trip's extra",doorT:"Sell at your door",doorK:"No truck needed",doorB:"Hauling would not pay you more than selling to a trader here.",doorP:"Selling at your door pays about",perkg:"That is about {v} a kg. If a trader offers much less, call your FPO before you sell.",ntK:"No truck is free for you",ntT:"Not this time",ntB:"Your {crop} were not given a truck. Do not wait at your farm for one.",ntP:"If you sell at your door, about",askF:"Ask your FPO what to do next.",call:"Call your FPO",out:"Log out",qLabel:"Trader's offer (₹ per kg)",qHaul:"Send the truck: it pays you more than this offer.",qSell:"Take the offer: it is better than the truck.",qDoorOk:"This offer is fine for selling at your door.",qDoorLow:"This is below the usual door price (about {v} a kg). Call your FPO before you sell.",ok:"OK",refresh:"Check again",exT:"Please log in again",exB:"For your safety the app logged you out. Your PIN is still the same.",lkT:"Too many wrong PINs",lkB:"Wait 15 minutes and try again, or ask your FPO for a new PIN.",nrT:"Your plan is not ready",nrB:"Your FPO has not shared the plan yet. Please check again later.",npT:"You are not in today's plan",npB:"Your produce is not part of the plan your FPO shared. If you have produce to sell, ask your FPO.",nsT:"No signal",nsB:"There is no saved card on this phone. Connect to the internet and log in.",farmer:"Farmer",net:"Could not reach the server. Try again.",stop:"Stop",newVer:"New version ready. Tap here to update.",kgw:"kilograms",fmt:"Farmer ID must be a number and PIN 6 digits.",srv:"Server problem (code {c}). Ask your FPO.",dis:"Farmer login is not switched on at the server yet. Ask your FPO.",inst:"Install app",instIos:"To install: tap Share, then Add to Home Screen.",noVoice:"This phone has no English voice. Open Settings > Language > Text-to-speech and install one.",phT:"Get updates on SMS and WhatsApp",phB:"We will message you when your truck time or payout changes.",phL:"Mobile number",phHint:"You will get a code by SMS and WhatsApp to check this number.",phSend:"Send code",phSkip:"Not now",phBad:"Enter a 10-digit mobile number.",phWait:"Please wait a minute and try again.",phFail:"Could not send the code. Try again later or ask your FPO.",otT:"Enter the code",otB:"We sent a 6-digit code to {n} on SMS and WhatsApp.",otL:"6-digit code",otOk:"Confirm",otBad:"That code is not right. Check and try again.",otOld:"That code has expired. Go back and ask for a new one.",otMany:"Too many wrong codes. Send a new code.",otFmt:"The code is 6 digits.",otChg:"Change number",otAgain:"Send code again",phOk:"Done. Updates will come to {n} on SMS and WhatsApp.",phOn:"SMS and WhatsApp updates: {n}",phRm:"Stop updates",phRmQ:"Stop SMS and WhatsApp updates to this number?",phAdd:"Get SMS and WhatsApp updates",phOff:"Updates stopped. Your number is deleted.",chat:"Ask for a change",cTitle:"Ask for a change",cHint:"Tell your FPO what changed: how many kg you have, or when your produce is ready.",cPh:"Example: 100 kg less",cSend:"Send",cUnd:"This is what I understood. Is it right?",cYes:"Yes, send to my FPO",cNo:"No, change it",cSent:"Sent to your FPO. The answer will show below.",cForm:"Use the form instead",cTxt:"Type a message instead",cFld:"What to change",cHow:"How",cVal:"Value",fQty:"Quantity",fReady:"Ready time",fDead:"Must leave by",hQs:"Make it (kg)",hQm:"Add (kg)",hQl:"Remove (kg)",hTs:"Set to (time)",hTm:"Later by (hours)",hTl:"Earlier by (hours)",cLlm:"I could not read that. Please use the form.",cBusy:"Please wait...",cClosed:"Changes are not open right now. Please call your FPO.",cMany:"Too many messages. Please wait, or call your FPO.",cStale:"Your details changed. Please send your request again.",cFail:"Something went wrong. Please try again.",cMine:"Your requests",cNone:"No requests yet.",cWd:"Cancel this request",sP:"Waiting for your FPO",sA:"Approved",sR:"Not possible",sW:"Cancelled",sE:"Expired",r1:"Too late",r2:"Not possible",r3:"No space in the trucks",r4:"Your FPO could not do it",e0:"Tell me what to change: how many kg, or which time.",e1:"You gave the same item twice. Send one value for it.",e2:"Quantity must be more than 0 and at most {m} kg.",e3:"The ready time cannot be before 00:00.",e4:"The deadline is too far away.",e5:"The ready time must be before the leaving time.",e6:"That is the same as your plan now. Nothing would change."},
te: {
 login:"లాగిన్",id:"రైతు ID",pin:"PIN",help:"మీ FPO ఇచ్చిన రైతు ID, PIN వాడండి.",wrong:"రైతు ID లేదా PIN తప్పు.",comes:"ట్రక్కు వచ్చే సమయం",takes:"మీ {kg} కిలోల {crop}ను మండీ {m}కు తీసుకెళ్తుంది.",changed:"గత ప్లాన్ తర్వాత మీకు కొన్ని మార్పులు జరిగాయి.",recv:"మీకు వచ్చేది సుమారు",est:"అంచనా",listen:"అంతా వినండి",offer:"వ్యాపారి ఆఫర్ చూడండి",day:"మీ రోజు",s1:"{t} ట్రక్కు మీ పొలానికి వస్తుంది",s1b:"మీ పంటను సిద్ధంగా ఉంచండి.",s2:"మండీ {m}లో అమ్మకం",s2b:"మీరు వెళ్లాల్సిన అవసరం లేదు.",map:"మ్యాప్‌లో చూడండి",s3:"చెల్లింపు: సుమారు {v}",s3b:"అమ్మకం తర్వాత మీ FPO చెల్లిస్తుంది.",how:"ఇది ఎలా లెక్కించారు",upd:"{t}కు నవీకరించబడింది. ఆఫ్‌లైన్‌లో పని చేస్తుంది.",offl:"సిగ్నల్ లేదు. ఇది {t} నాటి మీ కార్డ్.",old:"ఈ కార్డ్ ఒక రోజుకు పైగా పాతది. దీనిపై ఆధారపడకండి.",maybe:"అప్పటి నుంచి ప్లాన్ మారి ఉండవచ్చు. సిగ్నల్ ఉన్నప్పుడు మళ్లీ చూడండి.",back:"వెనుకకు",howT:"మీ {v} ఎలా లెక్కించారు",exact:"ఖచ్చితమైనది",derived:"లెక్కించినది",assumed:"ఊహించినది",dExact:"మీరు లేదా మీ FPO నమోదు చేసినది.",dDer:"మీ సంఖ్యలు, ట్రిప్ ఆధారంగా లెక్కించినది.",dAss:"వ్యాపారి మీ ఇంటి దగ్గర ఇచ్చే ధర అంచనా. అసలు ఆఫర్ వేరుగా ఉండవచ్చు.",doorsI:"ఇంటి వద్ద అమ్మితే విలువ",share:"ట్రిప్ అదనపు లాభంలో మీ వాటా",doorT:"ఇంటి వద్దే అమ్మండి",doorK:"ట్రక్కు అవసరం లేదు",doorB:"ఇక్కడ వ్యాపారికి అమ్మడం కంటే ట్రక్కులో పంపితే ఎక్కువ రాదు.",doorP:"ఇంటి వద్ద అమ్మితే సుమారు",perkg:"అది కిలోకు సుమారు {v}. వ్యాపారి చాలా తక్కువ ఇస్తే, అమ్మే ముందు మీ FPOకు ఫోన్ చేయండి.",ntK:"మీకు ట్రక్కు ఖాళీ లేదు",ntT:"ఈసారి కాదు",ntB:"మీ {crop}కు ట్రక్కు కేటాయించలేదు. ట్రక్కు కోసం పొలం దగ్గర ఎదురు చూడకండి.",ntP:"ఇంటి వద్ద అమ్మితే సుమారు",askF:"తర్వాత ఏం చేయాలో మీ FPOను అడగండి.",call:"మీ FPOకు ఫోన్ చేయండి",out:"లాగ్ అవుట్",qLabel:"వ్యాపారి ఆఫర్ (కిలోకు ₹)",qHaul:"ట్రక్కు పంపండి: ఈ ఆఫర్ కంటే ఎక్కువ వస్తుంది.",qSell:"ఆఫర్ తీసుకోండి: ట్రక్కు కంటే ఇదే మంచిది.",qDoorOk:"ఇంటి వద్ద అమ్మడానికి ఈ ఆఫర్ బాగుంది.",qDoorLow:"ఇది సాధారణ ఇంటి ధర (కిలోకు సుమారు {v}) కంటే తక్కువ. అమ్మే ముందు మీ FPOకు ఫోన్ చేయండి.",ok:"సరే",refresh:"మళ్లీ చూడండి",exT:"దయచేసి మళ్లీ లాగిన్ అవ్వండి",exB:"మీ భద్రత కోసం యాప్ లాగ్ అవుట్ చేసింది. మీ PIN అదే.",lkT:"చాలా తప్పు PINలు",lkB:"15 నిమిషాలు ఆగి మళ్లీ ప్రయత్నించండి, లేదా కొత్త PIN కోసం మీ FPOను అడగండి.",nrT:"మీ ప్లాన్ సిద్ధంగా లేదు",nrB:"మీ FPO ఇంకా ప్లాన్‌ను పంచుకోలేదు. దయచేసి తర్వాత మళ్లీ చూడండి.",npT:"మీరు ఈ రోజు ప్లాన్‌లో లేరు",npB:"మీ పంట మీ FPO పంచుకున్న ప్లాన్‌లో లేదు. అమ్మడానికి పంట ఉంటే మీ FPOను అడగండి.",nsT:"సిగ్నల్ లేదు",nsB:"ఈ ఫోన్‌లో సేవ్ చేసిన కార్డ్ లేదు. ఇంటర్నెట్‌కు కనెక్ట్ అయి లాగిన్ అవ్వండి.",farmer:"రైతు",net:"సర్వర్‌ను చేరుకోలేకపోయాం. మళ్లీ ప్రయత్నించండి.",stop:"ఆపండి",newVer:"కొత్త వెర్షన్ సిద్ధంగా ఉంది. అప్‌డేట్ చేయడానికి ఇక్కడ నొక్కండి.",kgw:"కిలోలు",fmt:"రైతు ID సంఖ్య, PIN 6 అంకెలు ఉండాలి.",srv:"సర్వర్ సమస్య (కోడ్ {c}). మీ FPOను అడగండి.",dis:"సర్వర్‌లో రైతు లాగిన్ ఇంకా ప్రారంభం కాలేదు. మీ FPOను అడగండి.",inst:"యాప్ ఇన్‌స్టాల్ చేయండి",instIos:"ఇన్‌స్టాల్ చేయడానికి: Share నొక్కి, తర్వాత Add to Home Screen ఎంచుకోండి.",noVoice:"ఈ ఫోన్‌లో తెలుగు వాయిస్ లేదు. ఫోన్ Settings > భాష > Text-to-speech లో దాన్ని ఇన్‌స్టాల్ చేయండి.",phT:"SMS, WhatsAppలో అప్‌డేట్‌లు పొందండి",phB:"మీ ట్రక్కు సమయం లేదా చెల్లింపు మారినప్పుడు మేము మీకు మెసేజ్ చేస్తాం.",phL:"మొబైల్ నంబర్",phHint:"ఈ నంబర్‌ను ధృవీకరించడానికి SMSలో కోడ్ వస్తుంది.",phSend:"కోడ్ పంపండి",phSkip:"ఇప్పుడు వద్దు",phBad:"10 అంకెల మొబైల్ నంబర్ ఇవ్వండి.",phWait:"ఒక నిమిషం ఆగి మళ్లీ ప్రయత్నించండి.",phFail:"కోడ్ పంపలేకపోయాం. తర్వాత మళ్లీ ప్రయత్నించండి లేదా మీ FPOను అడగండి.",otT:"కోడ్ ఇవ్వండి",otB:"{n}కు 6 అంకెల కోడ్ పంపాం.",otL:"6 అంకెల కోడ్",otOk:"నిర్ధారించండి",otBad:"కోడ్ తప్పు. చూసి మళ్లీ ప్రయత్నించండి.",otOld:"కోడ్ గడువు ముగిసింది. వెనక్కి వెళ్లి కొత్త కోడ్ అడగండి.",otMany:"చాలా తప్పు కోడ్‌లు. కొత్త కోడ్ పంపండి.",otFmt:"కోడ్ 6 అంకెలు ఉండాలి.",otChg:"నంబర్ మార్చండి",otAgain:"కోడ్ మళ్లీ పంపండి",phOk:"సరే. అప్‌డేట్‌లు {n}కు SMS, WhatsAppలో వస్తాయి.",phOn:"SMS, WhatsApp అప్‌డేట్‌లు: {n}",phRm:"అప్‌డేట్‌లు ఆపండి",phRmQ:"ఈ నంబర్‌కు SMS, WhatsApp అప్‌డేట్‌లు ఆపాలా?",phAdd:"SMS, WhatsApp అప్‌డేట్‌లు పొందండి",phOff:"అప్‌డేట్‌లు ఆగిపోయాయి. మీ నంబర్ తొలగించాం.",chat:"మార్పు అడగండి",cTitle:"మార్పు అడగండి",cHint:"మీ FPOకి ఏం మారిందో చెప్పండి: మీ దగ్గర ఎన్ని కిలోలు ఉన్నాయి, లేదా సరుకు ఎప్పుడు సిద్ధం.",cPh:"ఉదా: 100 కిలోలు తక్కువ",cSend:"పంపండి",cUnd:"నాకు అర్థమైంది ఇది. సరైనదేనా?",cYes:"అవును, నా FPOకి పంపండి",cNo:"కాదు, మార్చండి",cSent:"మీ FPOకి పంపాం. సమాధానం కింద కనిపిస్తుంది.",cForm:"బదులుగా ఫారం వాడండి",cTxt:"బదులుగా సందేశం టైప్ చేయండి",cFld:"ఏది మార్చాలి",cHow:"ఎలా",cVal:"విలువ",fQty:"పరిమాణం",fReady:"సిద్ధంగా ఉండే సమయం",fDead:"బయలుదేరాల్సిన సమయం",hQs:"ఇంత చేయండి (కిలోలు)",hQm:"కలపండి (కిలోలు)",hQl:"తగ్గించండి (కిలోలు)",hTs:"ఈ సమయానికి (సమయం)",hTm:"ఆలస్యం (గంటలు)",hTl:"ముందుగా (గంటలు)",cLlm:"నాకు అది అర్థం కాలేదు. దయచేసి ఫారం వాడండి.",cBusy:"దయచేసి వేచి ఉండండి...",cClosed:"ఇప్పుడు మార్పులు తీసుకోవడం లేదు. దయచేసి మీ FPOకి కాల్ చేయండి.",cMany:"చాలా సందేశాలు. కొంతసేపు ఆగండి, లేదా మీ FPOకి కాల్ చేయండి.",cStale:"మీ వివరాలు మారాయి. దయచేసి మళ్లీ అడగండి.",cFail:"ఏదో తప్పు జరిగింది. మళ్లీ ప్రయత్నించండి.",cMine:"మీ అభ్యర్థనలు",cNone:"ఇంకా అభ్యర్థనలు లేవు.",cWd:"ఈ అభ్యర్థన రద్దు చేయండి",sP:"FPO సమాధానం కోసం వేచి ఉంది",sA:"ఆమోదించారు",sR:"కుదరదు",sW:"రద్దు చేశారు",sE:"గడువు ముగిసింది",r1:"చాలా ఆలస్యం",r2:"కుదరదు",r3:"వాహనాల్లో చోటు లేదు",r4:"మీ FPO చేయలేకపోయారు",e0:"ఏం మార్చాలో చెప్పండి: ఎన్ని కిలోలు, లేదా ఏ సమయం.",e1:"ఒకే విషయాన్ని రెండుసార్లు చెప్పారు. దానికి ఒకే విలువ పంపండి.",e2:"పరిమాణం 0 కంటే ఎక్కువ, గరిష్ఠంగా {m} కిలోలు ఉండాలి.",e3:"సిద్ధంగా ఉండే సమయం 00:00 కంటే ముందు ఉండకూడదు.",e4:"చివరి సమయం చాలా దూరంగా ఉంది.",e5:"సిద్ధంగా ఉండే సమయం బయలుదేరే సమయానికి ముందు ఉండాలి.",e6:"ఇది మీ ప్రస్తుత ప్లాన్ లాగే ఉంది. ఏమీ మారదు."},
hi: {
 login:"लॉग इन",id:"किसान ID",pin:"PIN",help:"अपने FPO से मिला किसान ID और PIN डालें।",wrong:"किसान ID या PIN गलत है।",comes:"ट्रक आने का समय",takes:"यह आपके {kg} किलो {crop} को मंडी {m} ले जाएगा।",changed:"पिछले प्लान के बाद आपके लिए कुछ बदला है।",recv:"आपको लगभग मिलेंगे",est:"अनुमान",listen:"सब सुनें",offer:"व्यापारी का ऑफर जाँचें",day:"आपका दिन",s1:"{t} ट्रक आपके खेत पर आएगा",s1b:"अपनी उपज तैयार रखें।",s2:"मंडी {m} में बिक्री",s2b:"आपको जाने की ज़रूरत नहीं है।",map:"नक्शे पर खोलें",s3:"भुगतान: लगभग {v}",s3b:"बिक्री के बाद आपका FPO भुगतान करेगा।",how:"यह कैसे निकाला गया",upd:"{t} को अपडेट हुआ। ऑफ़लाइन भी चलता है।",offl:"सिग्नल नहीं है। यह {t} का आपका कार्ड है।",old:"यह कार्ड एक दिन से ज़्यादा पुराना है। इस पर भरोसा न करें।",maybe:"तब से प्लान बदल सकता है। सिग्नल आने पर फिर देखें।",back:"वापस",howT:"आपके {v} कैसे निकाले गए",exact:"सटीक",derived:"निकाला गया",assumed:"अनुमानित",dExact:"आपने या आपके FPO ने यह दर्ज किया।",dDer:"आपकी संख्याओं और ट्रिप से निकाला गया।",dAss:"आपके दरवाज़े पर व्यापारी के दाम का अनुमान। असली ऑफर अलग हो सकता है।",doorsI:"दरवाज़े पर बेचने का मूल्य",share:"ट्रिप के अतिरिक्त लाभ में आपका हिस्सा",doorT:"अपने दरवाज़े पर बेचें",doorK:"ट्रक की ज़रूरत नहीं",doorB:"यहाँ व्यापारी को बेचने से ट्रक भेजने पर ज़्यादा नहीं मिलेगा।",doorP:"दरवाज़े पर बेचने पर लगभग",perkg:"यह लगभग {v} प्रति किलो है। अगर व्यापारी बहुत कम दे, तो बेचने से पहले अपने FPO को फ़ोन करें।",ntK:"आपके लिए ट्रक खाली नहीं है",ntT:"इस बार नहीं",ntB:"आपके {crop} के लिए ट्रक नहीं मिला। ट्रक के इंतज़ार में खेत पर न रुकें।",ntP:"दरवाज़े पर बेचने पर लगभग",askF:"आगे क्या करें, अपने FPO से पूछें।",call:"अपने FPO को फ़ोन करें",out:"लॉग आउट",qLabel:"व्यापारी का ऑफर (₹ प्रति किलो)",qHaul:"ट्रक भेजें: इस ऑफर से ज़्यादा मिलेगा।",qSell:"ऑफर ले लें: यह ट्रक से बेहतर है।",qDoorOk:"दरवाज़े पर बेचने के लिए यह ऑफर ठीक है।",qDoorLow:"यह सामान्य दाम (लगभग {v} प्रति किलो) से कम है। बेचने से पहले अपने FPO को फ़ोन करें।",ok:"ठीक है",refresh:"फिर देखें",exT:"कृपया फिर से लॉग इन करें",exB:"आपकी सुरक्षा के लिए ऐप ने लॉग आउट कर दिया। आपका PIN वही है।",lkT:"बहुत ज़्यादा गलत PIN",lkB:"15 मिनट रुककर फिर कोशिश करें, या नए PIN के लिए अपने FPO से कहें।",nrT:"आपका प्लान तैयार नहीं है",nrB:"आपके FPO ने अभी प्लान साझा नहीं किया है। कृपया बाद में फिर देखें।",npT:"आप आज के प्लान में नहीं हैं",npB:"आपकी उपज आपके FPO के साझा प्लान में नहीं है। बेचने के लिए उपज हो तो अपने FPO से पूछें।",nsT:"सिग्नल नहीं है",nsB:"इस फ़ोन में कोई सेव किया कार्ड नहीं है। इंटरनेट से जुड़कर लॉग इन करें।",farmer:"किसान",net:"सर्वर तक नहीं पहुँच सके। फिर कोशिश करें।",stop:"रोकें",newVer:"नया वर्शन तैयार है। अपडेट करने के लिए यहाँ दबाएँ।",kgw:"किलो",fmt:"किसान ID संख्या और PIN 6 अंकों का होना चाहिए।",srv:"सर्वर की समस्या (कोड {c})। अपने FPO से पूछें।",dis:"सर्वर पर किसान लॉगिन अभी चालू नहीं है। अपने FPO से पूछें।",inst:"ऐप इंस्टॉल करें",instIos:"इंस्टॉल करने के लिए: Share दबाएँ, फिर Add to Home Screen चुनें।",noVoice:"इस फ़ोन में हिन्दी आवाज़ नहीं है। फ़ोन Settings > भाषा > Text-to-speech में उसे इंस्टॉल करें।",phT:"SMS और WhatsApp पर अपडेट पाएँ",phB:"ट्रक का समय या भुगतान बदलने पर हम आपको मैसेज करेंगे।",phL:"मोबाइल नंबर",phHint:"इस नंबर की जाँच के लिए SMS से कोड आएगा।",phSend:"कोड भेजें",phSkip:"अभी नहीं",phBad:"10 अंकों का मोबाइल नंबर डालें।",phWait:"एक मिनट रुककर फिर कोशिश करें।",phFail:"कोड नहीं भेज सके। बाद में फिर कोशिश करें या अपने FPO से पूछें।",otT:"कोड डालें",otB:"हमने {n} पर 6 अंकों का कोड भेजा है।",otL:"6 अंकों का कोड",otOk:"पक्का करें",otBad:"कोड सही नहीं है। जाँचकर फिर कोशिश करें।",otOld:"कोड की समय-सीमा खत्म हो गई। वापस जाकर नया कोड माँगें।",otMany:"बहुत ज़्यादा गलत कोड। नया कोड भेजें।",otFmt:"कोड 6 अंकों का होता है।",otChg:"नंबर बदलें",otAgain:"कोड फिर भेजें",phOk:"हो गया। अपडेट {n} पर SMS और WhatsApp से आएँगे।",phOn:"SMS और WhatsApp अपडेट: {n}",phRm:"अपडेट बंद करें",phRmQ:"इस नंबर पर SMS और WhatsApp अपडेट बंद करें?",phAdd:"SMS और WhatsApp अपडेट पाएँ",phOff:"अपडेट बंद हो गए। आपका नंबर हटा दिया गया।",chat:"बदलाव माँगें",cTitle:"बदलाव माँगें",cHint:"अपने FPO को बताएँ क्या बदला: आपके पास कितने किलो है, या माल कब तैयार है।",cPh:"जैसे: 100 किलो कम",cSend:"भेजें",cUnd:"मैंने यह समझा है। क्या यह सही है?",cYes:"हाँ, मेरे FPO को भेजें",cNo:"नहीं, बदलें",cSent:"आपके FPO को भेज दिया। जवाब नीचे दिखेगा।",cForm:"इसकी जगह फ़ॉर्म भरें",cTxt:"इसकी जगह संदेश लिखें",cFld:"क्या बदलना है",cHow:"कैसे",cVal:"मान",fQty:"मात्रा",fReady:"तैयार होने का समय",fDead:"निकलने का आख़िरी समय",hQs:"इतना करें (किलो)",hQm:"जोड़ें (किलो)",hQl:"घटाएँ (किलो)",hTs:"इस समय पर (समय)",hTm:"देर से (घंटे)",hTl:"जल्दी (घंटे)",cLlm:"मैं यह समझ नहीं पाया। कृपया फ़ॉर्म भरें।",cBusy:"कृपया प्रतीक्षा करें...",cClosed:"अभी बदलाव नहीं लिए जा रहे। कृपया अपने FPO को फ़ोन करें।",cMany:"बहुत ज़्यादा संदेश। थोड़ी देर रुकें, या अपने FPO को फ़ोन करें।",cStale:"आपकी जानकारी बदल गई है। कृपया फिर से भेजें।",cFail:"कुछ गड़बड़ हो गई। फिर कोशिश करें।",cMine:"आपके अनुरोध",cNone:"अभी कोई अनुरोध नहीं।",cWd:"यह अनुरोध रद्द करें",sP:"FPO के जवाब का इंतज़ार",sA:"मंज़ूर",sR:"नहीं हो सकता",sW:"रद्द किया",sE:"समय निकल गया",r1:"बहुत देर हो चुकी",r2:"नहीं हो सकता",r3:"गाड़ी में जगह नहीं",r4:"आपका FPO यह नहीं कर सका",e0:"बताएँ क्या बदलना है: कितने किलो, या कौन सा समय।",e1:"आपने एक ही चीज़ दो बार बताई। उसके लिए एक ही मान भेजें।",e2:"मात्रा 0 से ज़्यादा और अधिकतम {m} किलो होनी चाहिए।",e3:"तैयार होने का समय 00:00 से पहले नहीं हो सकता।",e4:"आख़िरी समय बहुत दूर है।",e5:"तैयार होने का समय निकलने के समय से पहले होना चाहिए।",e6:"यह आपकी मौजूदा योजना जैसा ही है। कुछ नहीं बदलेगा।"},
ta: {
 login:"உள்நுழை",id:"விவசாயி ID",pin:"PIN",help:"உங்கள் FPO கொடுத்த விவசாயி ID மற்றும் PIN-ஐப் பயன்படுத்துங்கள்.",wrong:"விவசாயி ID அல்லது PIN தவறு.",comes:"லாரி வரும் நேரம்",takes:"இது உங்கள் {kg} கிலோ {crop}-ஐ மண்டி {m}-க்கு கொண்டு செல்லும்.",changed:"கடைசி திட்டத்திற்குப் பிறகு உங்களுக்கு சில மாற்றங்கள் நடந்துள்ளன.",recv:"உங்களுக்கு கிடைப்பது சுமார்",est:"மதிப்பீடு",listen:"அனைத்தையும் கேளுங்கள்",offer:"வியாபாரியின் விலையைச் சரிபாருங்கள்",day:"உங்கள் நாள்",s1:"{t} லாரி உங்கள் வயலுக்கு வரும்",s1b:"உங்கள் விளைபொருளைத் தயாராக வையுங்கள்.",s2:"மண்டி {m}-இல் விற்பனை",s2b:"நீங்கள் போக வேண்டியதில்லை.",map:"வரைபடத்தில் திறக்கவும்",s3:"பணம்: சுமார் {v}",s3b:"விற்பனைக்குப் பிறகு உங்கள் FPO செலுத்தும்.",how:"இது எப்படிக் கணக்கிடப்பட்டது",upd:"{t}-க்கு புதுப்பிக்கப்பட்டது. இணையம் இல்லாமலும் வேலை செய்யும்.",offl:"சிக்னல் இல்லை. இது {t} நேரத்து உங்கள் கார்டு.",old:"இந்த கார்டு ஒரு நாளுக்கு மேல் பழையது. இதை நம்ப வேண்டாம்.",maybe:"அதற்குப் பிறகு திட்டம் மாறியிருக்கலாம். சிக்னல் கிடைத்ததும் மீண்டும் பாருங்கள்.",back:"பின்செல்",howT:"உங்கள் {v} எப்படிக் கணக்கிடப்பட்டது",exact:"துல்லியமானது",derived:"கணக்கிடப்பட்டது",assumed:"அனுமானம்",dExact:"நீங்கள் அல்லது உங்கள் FPO பதிவு செய்தது.",dDer:"உங்கள் எண்கள் மற்றும் பயணத்தை வைத்துக் கணக்கிடப்பட்டது.",dAss:"உங்கள் வீட்டு வாசலில் வியாபாரி கொடுக்கக்கூடிய விலையின் ஊகம். உண்மையான விலை வேறுபடலாம்.",doorsI:"வீட்டில் விற்றால் மதிப்பு",share:"பயணத்தின் கூடுதல் லாபத்தில் உங்கள் பங்கு",doorT:"வீட்டிலேயே விற்கவும்",doorK:"லாரி தேவையில்லை",doorB:"லாரியில் அனுப்பினால் இங்கே வியாபாரிக்கு விற்பதை விட அதிகம் கிடைக்காது.",doorP:"வீட்டில் விற்றால் சுமார்",perkg:"இது கிலோவுக்கு சுமார் {v}. வியாபாரி மிகக் குறைவாகக் கேட்டால், விற்பதற்கு முன் உங்கள் FPO-வுக்கு அழையுங்கள்.",ntK:"உங்களுக்கு லாரி இல்லை",ntT:"இந்த முறை இல்லை",ntB:"உங்கள் {crop}-க்கு லாரி ஒதுக்கப்படவில்லை. லாரிக்காக வயலில் காத்திருக்க வேண்டாம்.",ntP:"வீட்டில் விற்றால் சுமார்",askF:"அடுத்து என்ன செய்வது என்று உங்கள் FPO-விடம் கேளுங்கள்.",call:"உங்கள் FPO-வுக்கு அழையுங்கள்",out:"வெளியேறு",qLabel:"வியாபாரியின் விலை (கிலோவுக்கு ₹)",qHaul:"லாரியை அனுப்புங்கள்: இந்த விலையை விட அதிகம் கிடைக்கும்.",qSell:"இந்த விலையை ஏற்கலாம்: லாரியை விட இது நல்லது.",qDoorOk:"வீட்டில் விற்க இந்த விலை சரியானது.",qDoorLow:"இது வழக்கமான வீட்டு விலையை (கிலோவுக்கு சுமார் {v}) விடக் குறைவு. விற்பதற்கு முன் உங்கள் FPO-வுக்கு அழையுங்கள்.",ok:"சரி",refresh:"மீண்டும் பார்",exT:"மீண்டும் உள்நுழையுங்கள்",exB:"உங்கள் பாதுகாப்புக்காக செயலி உங்களை வெளியேற்றியது. உங்கள் PIN மாறவில்லை.",lkT:"அதிகமான தவறான PIN",lkB:"15 நிமிடம் காத்திருந்து மீண்டும் முயலுங்கள், அல்லது புதிய PIN-க்கு உங்கள் FPO-விடம் கேளுங்கள்.",nrT:"உங்கள் திட்டம் தயாராகவில்லை",nrB:"உங்கள் FPO இன்னும் திட்டத்தைப் பகிரவில்லை. பிறகு மீண்டும் பாருங்கள்.",npT:"இன்றைய திட்டத்தில் நீங்கள் இல்லை",npB:"உங்கள் விளைபொருள் உங்கள் FPO பகிர்ந்த திட்டத்தில் இல்லை. விற்க விளைபொருள் இருந்தால் உங்கள் FPO-விடம் கேளுங்கள்.",nsT:"சிக்னல் இல்லை",nsB:"இந்த போனில் சேமித்த கார்டு இல்லை. இணையத்தில் இணைந்து உள்நுழையுங்கள்.",farmer:"விவசாயி",net:"சர்வரை அடைய முடியவில்லை. மீண்டும் முயலுங்கள்.",stop:"நிறுத்து",newVer:"புதிய பதிப்பு தயாராக உள்ளது. புதுப்பிக்க இங்கே தொடுங்கள்.",kgw:"கிலோ",fmt:"விவசாயி ID எண்ணாகவும் PIN 6 இலக்கமாகவும் இருக்க வேண்டும்.",srv:"சர்வர் பிரச்சினை (குறியீடு {c}). உங்கள் FPO-விடம் கேளுங்கள்.",dis:"சர்வரில் விவசாயி உள்நுழைவு இன்னும் இயக்கப்படவில்லை. உங்கள் FPO-விடம் கேளுங்கள்.",inst:"செயலியை நிறுவுங்கள்",instIos:"நிறுவ: Share-ஐத் தொட்டு, பின் Add to Home Screen-ஐத் தேர்ந்தெடுங்கள்.",noVoice:"இந்த போனில் தமிழ் குரல் இல்லை. போன் Settings > மொழி > Text-to-speech-இல் அதை நிறுவுங்கள்.",phT:"SMS, WhatsApp-இல் அறிவிப்புகள் பெறுங்கள்",phB:"உங்கள் லாரி நேரம் அல்லது பணம் மாறினால் நாங்கள் செய்தி அனுப்புவோம்.",phL:"கைபேசி எண்",phHint:"இந்த எண்ணைச் சரிபார்க்க SMS-இல் ஒரு குறியீடு வரும்.",phSend:"குறியீட்டை அனுப்பு",phSkip:"இப்போது வேண்டாம்",phBad:"10 இலக்க கைபேசி எண்ணை உள்ளிடுங்கள்.",phWait:"ஒரு நிமிடம் காத்திருந்து மீண்டும் முயலுங்கள்.",phFail:"குறியீட்டை அனுப்ப முடியவில்லை. பிறகு முயலுங்கள் அல்லது உங்கள் FPO-விடம் கேளுங்கள்.",otT:"குறியீட்டை உள்ளிடுங்கள்",otB:"{n} எண்ணுக்கு 6 இலக்க குறியீட்டை அனுப்பினோம்.",otL:"6 இலக்க குறியீடு",otOk:"உறுதி செய்",otBad:"குறியீடு தவறு. சரிபார்த்து மீண்டும் முயலுங்கள்.",otOld:"குறியீடு காலாவதியாகிவிட்டது. பின்சென்று புதிய குறியீடு கேளுங்கள்.",otMany:"அதிகமான தவறான குறியீடுகள். புதிய குறியீட்டை அனுப்புங்கள்.",otFmt:"குறியீடு 6 இலக்கம்.",otChg:"எண்ணை மாற்று",otAgain:"குறியீட்டை மீண்டும் அனுப்பு",phOk:"முடிந்தது. அறிவிப்புகள் {n} எண்ணுக்கு SMS, WhatsApp-இல் வரும்.",phOn:"SMS, WhatsApp அறிவிப்புகள்: {n}",phRm:"அறிவிப்புகளை நிறுத்து",phRmQ:"இந்த எண்ணுக்கு SMS, WhatsApp அறிவிப்புகளை நிறுத்தவா?",phAdd:"SMS, WhatsApp அறிவிப்புகள் பெறுங்கள்",phOff:"அறிவிப்புகள் நிறுத்தப்பட்டன. உங்கள் எண் நீக்கப்பட்டது.",chat:"மாற்றம் கேளுங்கள்",cTitle:"மாற்றம் கேளுங்கள்",cHint:"உங்கள் FPO-விடம் என்ன மாறியது என்று சொல்லுங்கள்: உங்களிடம் எத்தனை கிலோ உள்ளது, அல்லது விளைபொருள் எப்போது தயார்.",cPh:"எ.கா: 100 கிலோ குறைவு",cSend:"அனுப்பு",cUnd:"எனக்குப் புரிந்தது இது. சரியா?",cYes:"ஆம், என் FPO-விற்கு அனுப்பு",cNo:"இல்லை, மாற்று",cSent:"உங்கள் FPO-விற்கு அனுப்பப்பட்டது. பதில் கீழே தெரியும்.",cForm:"அதற்குப் பதிலாக படிவத்தைப் பயன்படுத்துங்கள்",cTxt:"அதற்குப் பதிலாக செய்தி தட்டச்சு செய்யுங்கள்",cFld:"எதை மாற்ற வேண்டும்",cHow:"எப்படி",cVal:"மதிப்பு",fQty:"அளவு",fReady:"தயாராகும் நேரம்",fDead:"புறப்பட வேண்டிய நேரம்",hQs:"இவ்வளவாக்கு (கிலோ)",hQm:"கூட்டு (கிலோ)",hQl:"குறை (கிலோ)",hTs:"இந்த நேரத்துக்கு (நேரம்)",hTm:"தாமதம் (மணி)",hTl:"முன்னதாக (மணி)",cLlm:"எனக்கு அது புரியவில்லை. தயவுசெய்து படிவத்தைப் பயன்படுத்துங்கள்.",cBusy:"தயவுசெய்து காத்திருங்கள்...",cClosed:"இப்போது மாற்றங்கள் ஏற்கப்படுவதில்லை. தயவுசெய்து உங்கள் FPO-வை அழையுங்கள்.",cMany:"நிறைய செய்திகள். சிறிது நேரம் காத்திருங்கள், அல்லது உங்கள் FPO-வை அழையுங்கள்.",cStale:"உங்கள் விவரங்கள் மாறிவிட்டன. தயவுசெய்து மீண்டும் கேளுங்கள்.",cFail:"ஏதோ தவறு நடந்தது. மீண்டும் முயற்சிக்கவும்.",cMine:"உங்கள் கோரிக்கைகள்",cNone:"இன்னும் கோரிக்கைகள் இல்லை.",cWd:"இந்தக் கோரிக்கையை ரத்து செய்",sP:"FPO பதிலுக்காக காத்திருக்கிறது",sA:"ஒப்புக்கொள்ளப்பட்டது",sR:"இயலாது",sW:"ரத்து செய்யப்பட்டது",sE:"காலாவதியானது",r1:"மிகவும் தாமதம்",r2:"இயலாது",r3:"வாகனத்தில் இடம் இல்லை",r4:"உங்கள் FPO-வால் முடியவில்லை",e0:"என்ன மாற்ற வேண்டும் என்று சொல்லுங்கள்: எத்தனை கிலோ, அல்லது எந்த நேரம்.",e1:"ஒரே விஷயத்தை இரண்டு முறை சொன்னீர்கள். அதற்கு ஒரு மதிப்பு மட்டும் அனுப்புங்கள்.",e2:"அளவு 0-க்கு மேல், அதிகபட்சம் {m} கிலோ இருக்க வேண்டும்.",e3:"தயாராகும் நேரம் 00:00-க்கு முன் இருக்க முடியாது.",e4:"கடைசி நேரம் மிகவும் தொலைவில் உள்ளது.",e5:"தயாராகும் நேரம் புறப்படும் நேரத்துக்கு முன் இருக்க வேண்டும்.",e6:"இது உங்கள் தற்போதைய திட்டத்துக்கு சமம். எதுவும் மாறாது."}};
const CROP = { te:{tomato:"టమాటా",onion:"ఉల్లిపాయ",potato:"బంగాళాదుంప",cauliflower:"కాలిఫ్లవర్",mango:"మామిడి",spinach:"పాలకూర"}, hi:{tomato:"टमाटर",onion:"प्याज",potato:"आलू",cauliflower:"फूलगोभी",mango:"आम",spinach:"पालक"}, ta:{tomato:"தக்காளி",onion:"வெங்காயம்",potato:"உருளைக்கிழங்கு",cauliflower:"காலிஃபிளவர்",mango:"மாம்பழம்",spinach:"பசலைக்கீரை"} };
const SPEECH = { en:"en-IN", te:"te-IN", hi:"hi-IN", ta:"ta-IN" };
const IC = { chat:'<path d="M4 5h16v11H9l-5 4V5z"/>', stop:'<rect x="6" y="6" width="12" height="12" rx="2"/>', truck:'<path d="M3 7h11v9H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="17" r="1.6"/><circle cx="17" cy="17" r="1.6"/>', sp:'<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16 9a4 4 0 010 6"/>', pin:'<path d="M12 21s6-5.5 6-10a6 6 0 10-12 0c0 4.5 6 10 6 10z"/><circle cx="12" cy="11" r="2"/>', phone:'<path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2z"/>', off:'<path d="M2 8.8a15 15 0 0120 0M5 12.5a10 10 0 0114 0M8.5 16a5 5 0 017 0M12 19.5v.5M3 3l18 18"/>', alert:'<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>', lock:'<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>', clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', user:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/>' };
const S = { lang: L[localStorage.lang] ? localStorage.lang : "en", token: localStorage.token || "", card: JSON.parse(localStorage.card || "null"), at: +localStorage.cardAt || 0, view: "boot", msg: "", err: "", online: true };
const esc = x => String(x).replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const t = (k, v = {}) => (L[S.lang][k] || L.en[k]).replace(/\{(\w+)\}/g, (_, n) => v[n] ?? "");
const ic = n => `<svg aria-hidden="true" viewBox="0 0 24 24">${IC[n]}</svg>`;
const rs = v => "₹" + Math.round(v).toLocaleString("en-IN");
const t12 = e => { const m = /^(\d{1,2}):(\d{2})$/.exec(e || ""); if (!m) return { t: String(e || ""), p: "", h: 0, m: 0 }; const h = +m[1] % 24; return { t: `${h % 12 || 12}:${m[2]}`, p: h < 12 ? "AM" : "PM", h: h % 12 || 12, m: +m[2], h24: h }; };   // plan time "13:05" -> 1:05 PM
const tshow = e => { const x = t12(e); return x.p ? `${x.t} ${x.p}` : x.t; };
const crop = c => (CROP[S.lang] || {})[c] || c;
const clock = ms => new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const phone = () => (S.card && S.card.fpo_phone) || localStorage.fpoPhone || "";
const langBar = () => `<div class="lang">${[["en","English"],["te","తెలుగు"],["hi","हिन्दी"],["ta","தமிழ்"]].map(([k,n]) => `<button data-lang="${k}" class="${S.lang===k?"on":""}">${n}</button>`).join("")}</div>`;
const btn = (act, label, cls, icon) => `<button class="btn ${cls}" data-act="${act}">${icon ? ic(icon) : ""}${label}</button>`;
const callBtn = () => phone() ? `<a class="btn amber" href="tel:${esc(phone())}">${ic("phone")}${t("call")}</a>` : "";
let deferred = null;   // Chrome's install prompt, kept so our own button can show it
const standalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const instUI = () => standalone() ? "" : deferred ? btn("install", t("inst"), "line") : /iphone|ipad|ipod/i.test(navigator.userAgent) ? `<div class="note">${t("instIos")}</div>` : "";
const typing = () => ["#fid", "#pin", "#q", "#ph", "#otp", "#cq", "#cv"].some(s => $(s) && $(s).value);
addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferred = e; if (S.view !== "boot" && !typing()) render(); });
addEventListener("appinstalled", () => { deferred = null; if (S.view !== "boot" && !typing()) render(); });
let spk = false;   // true while the phone is reading aloud
const lis = cls => btn("listen", t(spk ? "stop" : "listen"), cls, spk ? "stop" : "sp");
function setSpk(v) { spk = v; document.querySelectorAll("[data-act=listen]").forEach(b => { b.innerHTML = ic(v ? "stop" : "sp") + t(v ? "stop" : "listen"); }); }
function hush() { if (window.speechSynthesis) speechSynthesis.cancel(); setSpk(false); }
const upd = () => `<span class="note">${t("upd", { t: clock(S.at) })}</span>`;

const phoneRow = c => !S.online || !c.phone ? "" : c.phone.registered ? `<span class="note">${t("phOn", { n: esc(c.phone.masked || "") })}</span><button class="link" data-act="phRm" style="font-weight:400">${t("phRm")}</button>` : `<button class="link" data-act="phAdd" style="font-weight:400">${t("phAdd")}</button>`;
const skipKey = () => "phoneSkip" + (S.card ? S.card.farmer_id : "");   // "Not now" is remembered per farmer for 3 days
const wantPhone = () => S.online && S.card && S.card.phone && !S.card.phone.registered && Date.now() - (+localStorage[skipKey()] || 0) > 3 * 864e5;
const authed = (p, o = {}) => fetch(API + p, { ...o, headers: { "Content-Type": "application/json", Authorization: "Bearer " + S.token } });

function views() {
  const c = S.card;
  if (S.view === "chat") return chatView();
  if (S.view === "login") return `<div class="body"><div class="row"><span class="note">Farmroute</span>${langBar()}</div><h1 class="mid" style="margin:18px 0 0">${t("login")}</h1><span class="note" style="font-size:17px">${t("help")}</span>
   <label>${t("id")}<input id="fid" inputmode="numeric" autocomplete="username" value="${esc(localStorage.fid || "")}"></label><label>${t("pin")}<input id="pin" inputmode="numeric" maxlength="6" type="password" autocomplete="current-password"></label>
   ${S.err ? `<div class="err" role="alert">${esc(S.err)}</div>` : ""}<div class="col" style="margin-top:auto;gap:12px">${instUI()}${btn("login", t("login"), "green")}</div></div>`;
  if (S.view === "msg") { const [i, k] = S.msg.split(":"); return `<div class="body"><div class="row"><span class="note">Farmroute</span>${langBar()}</div><div class="ico">${ic(i)}</div><h1 class="mid" style="font-size:32px;margin-top:10px">${t(k+"T")}</h1><p style="font-size:19px;margin:0">${t(k+"B")}</p>
   <div class="col" style="margin-top:auto">${k==="lk"?callBtn()+btn("login0", t("ok"), "line"):k==="nr"?btn("refresh", t("refresh"), "amber"):k==="np"?callBtn():btn("login0", t("login"), "amber")}</div></div>`; }
  if (S.view === "slip") { const ln = k => (c.payout.lines.find(l => l.key === k) || {}).value;
   return `<div class="body"><div class="row"><button class="link" data-act="home">‹ ${t("back")}</button>${langBar()}</div><h1 class="mid" style="font-size:30px">${t("howT", { v: rs(c.payout.total_inr) })}</h1>
   <section class="slip"><div class="row"><span>${esc(crop(c.crop))}<br><span class="note">${c.qty_kg} kg</span></span><span class="tag" style="color:#1E4D3A">${t("exact")}</span></div>
   <div class="row"><span>${t("doorsI")}<br><b>${rs(ln("doorstep_value"))}</b></span><span class="tag" style="color:#8A5A00">${t("assumed")}</span></div>
   ${ln("trip_share") != null ? `<div class="row"><span>${t("share")}<br><b>+ ${rs(ln("trip_share"))}</b></span><span class="tag" style="color:#1F5F8B">${t("derived")}</span></div>` : ""}
   <div style="padding-top:12px" class="note">${t("recv")}<div class="mid" style="color:#1E4D3A">${rs(c.payout.total_inr)}</div></div></section>
   <dl class="col" style="margin:0;gap:12px"><div><dt><b>${t("exact")}</b></dt><dd style="margin:0">${t("dExact")}</dd></div><div><dt><b>${t("derived")}</b></dt><dd style="margin:0">${t("dDer")}</dd></div><div><dt><b>${t("assumed")}</b></dt><dd style="margin:0">${t("dAss")}</dd></div></dl>
   <div style="margin-top:auto">${lis("amber")}</div></div>`; }
  if (S.view === "quote") return `<div class="body"><div class="row"><button class="link" data-act="home">‹ ${t("back")}</button>${langBar()}</div><h1 class="mid" style="font-size:30px">${t("offer")}</h1>
   <label>${t("qLabel")}<input id="q" inputmode="decimal" autofocus></label><div id="verdict" class="ban" aria-live="polite" style="min-height:64px;font-size:18px;font-weight:600"></div></div>`;
  if (S.view === "phone" || S.view === "otp") { const ph = S.view === "phone", err = S.err ? `<div class="err" role="alert">${esc(S.err)}</div>` : "";
   return `<div class="body"><div class="row"><span class="note">Farmroute</span>${langBar()}</div><div class="ico" style="margin-top:12px">${ic("phone")}</div><h1 class="mid" style="font-size:32px;margin:6px 0 0">${t(ph ? "phT" : "otT")}</h1><span class="note" style="font-size:17px">${ph ? t("phB") : t("otB", { n: esc(S.masked || "") })}</span>
   ${ph ? `<label>${t("phL")}<input id="ph" type="tel" inputmode="tel" autocomplete="tel" placeholder="98765 43210" style="letter-spacing:.05em" value="${esc(S.ph || "")}"></label><span class="note">${t("phHint")}</span>`
        : `<label>${t("otL")}<input id="otp" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="••••••"></label>${S.demo ? `<div class="note" role="status">Demo mode, no SMS sent. Code: <strong>${esc(S.demo)}</strong></div>` : ""}`}
   ${err}<div class="col" style="margin-top:auto;gap:12px">${ph ? btn("phSend", t("phSend"), "green") + btn("phSkip", t("phSkip"), "line") : btn("phVerify", t("otOk"), "green") + btn("phSend", t("otAgain"), "line") + btn("phChg", t("otChg"), "line")}</div></div>`; }
  // card
  const st = c.status, tr = c.trip, hd = st === "hauled" ? "" : st === "unserved" ? " warn" : "";
  const kicker = st === "hauled" ? [ "truck", t("comes") ] : st === "farmgate" ? [ "pin", t("doorK") ] : [ "alert", t("ntK") ];
  const big = st === "hauled" ? `<b class="big">${t12(tr.pickup_eta).t}<small>${t12(tr.pickup_eta).p}</small></b>` : `<b class="mid">${st === "farmgate" ? t("doorT") : t("ntT")}</b>`;
  const sub = st === "hauled" ? t("takes", { kg: c.qty_kg, crop: crop(c.crop), m: (tr.mandis[0] || {}).id }) : st === "farmgate" ? t("doorB") : t("ntB", { crop: crop(c.crop) });
  const age = (Date.now() - S.at) / 36e5;
  const offBar = S.online ? "" : `<div class="off" role="status">${ic("off")}<span>${age > STALE_H ? t("old") : t("offl", { t: clock(S.at) })}</span></div>`;
  const door = c.doorstep_per_kg, total = rs(c.payout.total_inr);
  const money = st === "hauled" ? `<div><span class="note" style="font-size:16px">${t("recv")}</span><div class="mid">${total} <span class="tag" style="color:#8A5A00;vertical-align:middle;font-size:12px">${t("est")}</span></div></div>`
    : `<div><span class="note" style="font-size:16px">${st === "farmgate" ? t("doorP") : t("ntP")}</span><div class="mid">${total} <span class="tag" style="color:#8A5A00;vertical-align:middle;font-size:12px">${t("assumed")}</span></div></div>`;
  const day = st !== "hauled" ? "" : `<div class="side" style="padding:8px 20px 0;border-top:1px solid #D5DED8"><h2 style="font-size:24px;margin:18px 0 16px">${t("day")}</h2>
   <div class="step"><div class="sc"><span class="dot f">${ic("truck")}</span><span class="ln"></span></div><div style="padding-bottom:26px"><b style="font-size:20px">${t("s1", { t: esc(tshow(tr.pickup_eta)) })}</b><div class="note" style="font-size:16px">${t("s1b")}</div></div></div>
   <div class="step"><div class="sc"><span class="dot">${ic("pin")}</span><span class="ln"></span></div><div style="padding-bottom:26px"><b style="font-size:20px">${t("s2", { m: (tr.mandis[0] || {}).id })}</b><div class="note" style="font-size:16px">${t("s2b")}</div>${tr.mandis[0] ? `<a class="link" target="_blank" rel="noopener" href="https://www.google.com/maps/search/?api=1&query=${tr.mandis[0].lat},${tr.mandis[0].lng}">${t("map")}</a>` : ""}</div></div>
   <div class="step"><span class="dot">₹</span><div><b style="font-size:20px">${t("s3", { v: total })}</b><div class="note" style="font-size:16px">${t("s3b")}</div></div></div></div>`;
  return `${offBar}<div class="card ${st === "hauled" ? "two" : "one"}"><div class="main"><div class="hd${hd}"><div class="row"><span style="font-size:15px">${t("farmer")} ${c.farmer_id}</span>${langBar()}</div><span style="margin-top:14px;display:flex;gap:8px;align-items:center;font-size:18px">${ic(kicker[0])}${kicker[1]}</span>${big}<span style="font-size:18px">${sub}</span></div>
   <div class="body" style="flex:none">${c.changed && c.changed.length ? `<div class="ban"><b>${t("changed")}</b></div>` : ""}${money}
   ${st === "farmgate" ? `<div class="note" style="font-size:16px">${t("perkg", { v: rs(door) })}</div>` : ""}${st === "unserved" ? `<div class="note" style="font-size:16px">${t("askF")}</div>${callBtn()}` : ""}
   ${st === "hauled" ? lis("amber") : btn("quote", t("offer"), "amber") + lis("line")}${st === "hauled" ? btn("quote", t("offer"), "line") : ""}</div></div>${day}
   <div class="foot" style="padding:0 20px calc(24px + env(safe-area-inset-bottom));display:flex;flex-direction:column;gap:6px;margin-top:auto;padding-top:26px"><button class="link" data-act="slip" style="justify-content:space-between;border-top:1px solid #D5DED8;width:100%;min-height:52px;font-size:17px;color:#14231B;font-weight:400">${t("how")} <span aria-hidden="true">›</span></button>${phoneRow(c)}${instUI()}${upd()}<button class="link" data-act="logout" style="font-weight:400">${t("out")}</button></div></div>`;
}
function render() { $("#app").className = S.view === "card" && S.card && S.card.status === "hauled" ? "wide" : ""; $("#app").innerHTML = views(); document.documentElement.lang = S.lang; if (S.view === "quote") $("#q").addEventListener("input", verdict); fab(); chatFocus(); }
function verdict() {
  const q = parseFloat($("#q").value), c = S.card, el = $("#verdict"); if (!(q > 0)) { el.textContent = ""; return; }
  el.textContent = c.status === "hauled" ? (q < c.break_even_per_kg ? t("qHaul") : t("qSell")) : (q >= c.doorstep_per_kg ? t("qDoorOk") : t("qDoorLow", { v: rs(c.doorstep_per_kg) }));
}
const vlang = x => (x.lang || "").replace("_", "-").toLowerCase();
const voices = () => new Promise(res => {   // Chrome loads voices late: getVoices() is empty on first call
  const ss = speechSynthesis, v = ss.getVoices(); if (v.length) return res(v);
  const f = () => { ss.removeEventListener("voiceschanged", f); res(ss.getVoices()); };
  ss.addEventListener("voiceschanged", f); setTimeout(f, 1500);
});
function toast(m) { const el = $("#sp"); el.textContent = m; el.hidden = false; clearTimeout(toast.h); toast.reload = false; toast.h = setTimeout(() => { if (!toast.reload) el.hidden = true; }, 10000); }
// Spoken scripts: written to sound like a person talking, not the on-screen labels read out. One idea per sentence.
const SAY = {
 en:{ pd:["", "", "", ""], t0:"{h} {ap}", t1:"{h}:{mm} {ap}", up:"Please note, something has changed for you since the last plan.",
  hauled:"Good news. A truck will come to your farm at {t}. It will take your {kg} kilos of {crop} to Mandi {m}. You do not need to go anywhere. After the sale, your FPO will pay you about {v} rupees. That is an estimate, not a promise.",
  farmgate:"You do not need a truck this time. Selling to a trader at your door pays about as much as sending it by truck. You should get about {v} rupees, that is about {p} rupees a kilo. If a trader offers much less, call your FPO before you sell.",
  unserved:"Sorry, no truck is free for your {crop} this time. Please do not wait at your farm for one. If you sell to a trader at your door, you may get about {v} rupees. Ask your FPO what to do next.",
  slip:"Here is how your {v} rupees is worked out. You have {kg} kilos of {crop}. You or your FPO entered that number. If you sold at your door, a trader would pay about {d} rupees. That is only a guess, a real offer can differ. {share}In total, you receive about {v} rupees.",
  share:"Sending it by truck adds a share of about {s} rupees from the trip. " },
 te:{ pd:["ఉదయం","మధ్యాహ్నం","సాయంత్రం","రాత్రి"], t0:"{pd} {h} గంటలకు", t1:"{pd} {h} గంటల {m} నిమిషాలకు", up:"గమనించండి, గత ప్లాన్ తర్వాత మీకు కొన్ని మార్పులు జరిగాయి.",
  hauled:"శుభవార్త. {t} ట్రక్కు మీ పొలానికి వస్తుంది. అది మీ {kg} కిలోల {crop}ను మండీ {m}కు తీసుకెళ్తుంది. మీరు ఎక్కడికీ వెళ్లాల్సిన అవసరం లేదు. అమ్మకం తర్వాత, మీ FPO మీకు సుమారు {v} రూపాయలు చెల్లిస్తుంది. ఇది అంచనా మాత్రమే, హామీ కాదు.",
  farmgate:"ఈసారి మీకు ట్రక్కు అవసరం లేదు. ట్రక్కులో పంపినా, ఇంటి వద్ద వ్యాపారికి అమ్మినా దాదాపు ఒకటే వస్తుంది. ఇంటి వద్ద అమ్మితే మీకు సుమారు {v} రూపాయలు వస్తాయి, అంటే కిలోకు సుమారు {p} రూపాయలు. వ్యాపారి చాలా తక్కువ ఇస్తే, అమ్మే ముందు మీ FPOకు ఫోన్ చేయండి.",
  unserved:"క్షమించండి, ఈసారి మీ {crop}కు ట్రక్కు ఖాళీ లేదు. ట్రక్కు కోసం పొలం దగ్గర ఎదురు చూడకండి. ఇంటి వద్ద వ్యాపారికి అమ్మితే మీకు సుమారు {v} రూపాయలు రావచ్చు. తర్వాత ఏం చేయాలో మీ FPOను అడగండి.",
  slip:"మీ {v} రూపాయలు ఎలా లెక్కించారో చెబుతాను. మీకు {kg} కిలోల {crop} ఉంది. ఈ సంఖ్యను మీరు లేదా మీ FPO నమోదు చేశారు. ఇంటి వద్ద అమ్మితే వ్యాపారి సుమారు {d} రూపాయలు ఇస్తాడు. ఇది ఊహ మాత్రమే, అసలు ఆఫర్ వేరుగా ఉండవచ్చు. {share}మొత్తం మీకు సుమారు {v} రూపాయలు వస్తాయి.",
  share:"ట్రక్కులో పంపడం వల్ల ట్రిప్ నుంచి అదనంగా సుమారు {s} రూపాయల వాటా వస్తుంది. " },
 hi:{ pd:["सुबह","दोपहर","शाम","रात"], t0:"{pd} {h} बजे", t1:"{pd} {h} बजकर {m} मिनट पर", up:"ध्यान दें, पिछले प्लान के बाद आपके लिए कुछ बदला है।",
  hauled:"अच्छी खबर। {t} आपके खेत पर ट्रक आएगा। वह आपके {kg} किलो {crop} को मंडी {m} ले जाएगा। आपको कहीं जाने की ज़रूरत नहीं है। बिक्री के बाद, आपका FPO आपको लगभग {v} रुपये देगा। यह सिर्फ़ अनुमान है, पक्का वादा नहीं।",
  farmgate:"इस बार आपको ट्रक की ज़रूरत नहीं है। ट्रक से भेजने पर भी लगभग उतना ही मिलेगा जितना यहाँ व्यापारी को बेचने पर। दरवाज़े पर बेचने से आपको लगभग {v} रुपये मिलेंगे, यानी लगभग {p} रुपये किलो। अगर व्यापारी बहुत कम दे, तो बेचने से पहले अपने FPO को फ़ोन करें।",
  unserved:"माफ़ कीजिए, इस बार आपके {crop} के लिए कोई ट्रक खाली नहीं है। ट्रक के इंतज़ार में खेत पर न रुकें। दरवाज़े पर व्यापारी को बेचने पर आपको लगभग {v} रुपये मिल सकते हैं। आगे क्या करना है, अपने FPO से पूछें।",
  slip:"आपके {v} रुपये कैसे निकाले गए, सुनिए। आपके पास {kg} किलो {crop} है। यह संख्या आपने या आपके FPO ने दर्ज की है। दरवाज़े पर बेचने पर व्यापारी लगभग {d} रुपये देगा। यह सिर्फ़ अनुमान है, असली ऑफर अलग हो सकता है। {share}कुल मिलाकर आपको लगभग {v} रुपये मिलेंगे।",
  share:"ट्रक से भेजने पर ट्रिप से लगभग {s} रुपये का अतिरिक्त हिस्सा मिलता है। " },
 ta:{ pd:["காலை","மதியம்","மாலை","இரவு"], t0:"{pd} {h} மணிக்கு", t1:"{pd} {h} மணி {m} நிமிடத்திற்கு", up:"கவனியுங்கள், கடைசி திட்டத்திற்குப் பிறகு உங்களுக்கு சில மாற்றங்கள் நடந்துள்ளன.",
  hauled:"நல்ல செய்தி. {t} லாரி உங்கள் வயலுக்கு வரும். அது உங்கள் {kg} கிலோ {crop}-ஐ மண்டி {m}-க்கு கொண்டு செல்லும். நீங்கள் எங்கும் போக வேண்டியதில்லை. விற்பனைக்குப் பிறகு, உங்கள் FPO உங்களுக்கு சுமார் {v} ரூபாய் கொடுக்கும். இது ஒரு மதிப்பீடு மட்டுமே, உறுதியான தொகை அல்ல.",
  farmgate:"இந்த முறை உங்களுக்கு லாரி தேவையில்லை. லாரியில் அனுப்பினாலும், இங்கே வியாபாரிக்கு விற்றாலும் கிட்டத்தட்ட ஒரே தொகைதான் கிடைக்கும். வீட்டில் விற்றால் உங்களுக்கு சுமார் {v} ரூபாய் கிடைக்கும், அதாவது கிலோவுக்கு சுமார் {p} ரூபாய். வியாபாரி மிகக் குறைவாகக் கேட்டால், விற்பதற்கு முன் உங்கள் FPO-வுக்கு அழையுங்கள்.",
  unserved:"மன்னிக்கவும், இந்த முறை உங்கள் {crop}-க்கு லாரி இல்லை. லாரிக்காக வயலில் காத்திருக்க வேண்டாம். வீட்டில் வியாபாரிக்கு விற்றால் உங்களுக்கு சுமார் {v} ரூபாய் கிடைக்கலாம். அடுத்து என்ன செய்வது என்று உங்கள் FPO-விடம் கேளுங்கள்.",
  slip:"உங்கள் {v} ரூபாய் எப்படிக் கணக்கிடப்பட்டது என்று சொல்கிறேன். உங்களிடம் {kg} கிலோ {crop} உள்ளது. இந்த எண்ணை நீங்கள் அல்லது உங்கள் FPO பதிவு செய்தீர்கள். வீட்டில் விற்றால் வியாபாரி சுமார் {d} ரூபாய் கொடுப்பார். இது ஒரு ஊகம் மட்டுமே, உண்மையான விலை வேறுபடலாம். {share}மொத்தத்தில் உங்களுக்கு சுமார் {v} ரூபாய் கிடைக்கும்.",
  share:"லாரியில் அனுப்புவதால் பயணத்தில் இருந்து கூடுதலாக சுமார் {s} ரூபாய் பங்கு கிடைக்கும். " } };
const fill = (str, v) => str.replace(/\{(\w+)\}/g, (_, n) => v[n] ?? "");
const about = n => { n = Math.round(n); return (n >= 1000 ? Math.round(n / 10) * 10 : n >= 100 ? Math.round(n / 5) * 5 : n).toLocaleString("en-IN"); };   // "about 4,200", not "4,201"
function lines() {   // what to read for the screen the farmer is on
  const c = S.card, tr = c.trip || {}, X = SAY[S.lang] || SAY.en, m = (tr.mandis && tr.mandis[0] || {}).id;
  const tm = t12(tr.pickup_eta), h24 = tm.h24 || 0, pd = X.pd[h24 < 4 || h24 >= 20 ? 3 : h24 < 12 ? 0 : h24 < 16 ? 1 : 2];   // morning / afternoon / evening / night
  const when = !tm.p ? tm.t : fill(tm.m ? X.t1 : X.t0, { h: tm.h, m: tm.m, mm: String(tm.m).padStart(2, "0"), ap: tm.p, pd });
  const ln = k => (c.payout.lines.find(l => l.key === k) || {}).value, sh = ln("trip_share");
  const v = { t: when, kg: c.qty_kg, crop: crop(c.crop), m, v: about(c.payout.total_inr), p: Math.round(c.doorstep_per_kg || 0).toLocaleString("en-IN"),
    d: about(ln("doorstep_value") || 0), s: sh != null ? about(sh) : "", share: sh != null ? fill(X.share, { s: about(sh) }) : "" };
  const text = S.view === "slip" ? X.slip : X[c.status] || X.unserved;
  const intro = S.view !== "slip" && c.changed && c.changed.length ? X.up + " " : "";
  return (intro + fill(text, v)).replace(/([.।!?])\s+/g, "$1\u0001").split("\u0001");   // one utterance per sentence = natural pauses
}
async function speak() {
  if (spk) return hush();   // pressed again while reading: stop
  if (!("speechSynthesis" in window)) return toast(t("noVoice"));
  const lang = S.lang, code = SPEECH[lang], base = code.split("-")[0], view = S.view;
  const parts = lines().map(x => String(x == null ? "" : x).replace(/-(?=[\u0B80-\u0BFF])/g, "")).filter(Boolean);   // Tamil case-suffix hyphen is not spoken
  setSpk(true);
  const vs = await voices(), score = x => (vlang(x) === code.toLowerCase() ? 4 : 0) + (/network|online|neural|natural|enhanced|premium|wavenet/i.test(x.name + x.voiceURI) ? 2 : 0) - (/compact|espeak/i.test(x.name + x.voiceURI) ? 3 : 0),
    v = vs.filter(x => vlang(x).split("-")[0] === base).sort((a, b) => score(b) - score(a))[0];   // best-sounding voice for the language, not just the first
  if (!spk) return;   // stopped while voices were loading
  if (!v && vs.length && lang !== "en") { setSpk(false); return toast(t("noVoice")); }   // never read Telugu/Tamil/Hindi with an English voice
  const ss = speechSynthesis, busy = ss.speaking || ss.pending; ss.cancel(); speak.keep = [];   // keep refs: Chrome drops utterances that get garbage-collected
  setTimeout(() => {   // Android Chrome ignores speak() straight after cancel()
    if (!spk) return;
    let started = false;
    parts.forEach((p, i) => { const u = new SpeechSynthesisUtterance(p); u.lang = v ? v.lang : code; if (v) u.voice = v; u.rate = .92; u.pitch = 1;
      u.onstart = () => { started = true; };
      u.onend = () => { if (i === parts.length - 1) setSpk(false); };
      u.onerror = ev => { if (ev.error !== "interrupted" && ev.error !== "canceled") { setSpk(false); toast(t("noVoice")); } };
      speak.keep.push(u); ss.speak(u); });
    setTimeout(() => { if (!started && !ss.speaking && spk) { setSpk(false); toast(t("noVoice")); } }, 4000);
  }, busy ? 120 : 0);
}
function clear() { ["token", "card", "cardAt"].forEach(k => localStorage.removeItem(k)); S.token = ""; S.card = null; S.at = 0; S.chat = null; }   // shared phones: nothing of the last farmer stays
async function load() {
  try {
    const r = await fetch(API + "/farmer/me", { headers: { Authorization: "Bearer " + S.token } }); S.online = true;
    if (r.ok) { S.card = await r.json(); S.at = Date.now(); localStorage.card = JSON.stringify(S.card); localStorage.cardAt = S.at; if (S.card.fpo_phone) localStorage.fpoPhone = S.card.fpo_phone; S.view = S.view === "phone" || S.view === "otp" || S.view === "chat" ? S.view : wantPhone() ? "phone" : "card"; }
    else if (r.status === 401) { clear(); S.view = "msg"; S.msg = "user:ex"; }
    else { const d = (await r.json().catch(() => ({}))).detail || ""; S.view = "msg"; S.msg = /published/i.test(d) ? "clock:nr" : "alert:np"; }
  } catch { S.online = false; S.view = S.card ? "card" : "msg"; S.msg = "off:ns"; }
  render();
}
async function login() {
  const id = $("#fid").value.trim(), pin = $("#pin").value.trim(); S.err = "";
  if (!API || /YOUR-BACKEND/.test(API)) { S.err = t("srv", { c: "config.js" }); return render(); }   // backend URL never set
  if (!/^\d+$/.test(id) || !/^\d{6}$/.test(pin)) { S.err = t("fmt"); return render(); }
  try {
    const r = await fetch(API + "/farmer/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ farmer_id: +id, pin }) });
    if (r.ok) { clear(); S.token = localStorage.token = (await r.json()).token; localStorage.fid = id; S.view = "boot"; return load(); }
    if (r.status === 429) { S.view = "msg"; S.msg = "lock:lk"; }
    else if (r.status === 401) S.err = t("wrong");
    else if (r.status === 422) S.err = t("fmt");
    else if (r.status === 503) S.err = t("dis");
    else { console.error("login failed", r.status, API); S.err = t("srv", { c: r.status }); }   // 404 here = wrong backend address in config.js
  } catch { S.err = t("net"); }
  render();
}

const ex = () => { clear(); S.view = "msg"; S.msg = "user:ex"; };
async function phSend() {   // asks the server to text a code; nothing is stored until the code comes back right
  const v = ($("#ph") ? $("#ph").value : S.ph || "").trim(); S.ph = v; S.err = "";
  if (v.replace(/\D/g, "").length < 8) { S.err = t("phBad"); return render(); }
  try {
    const r = await authed("/farmer/phone/start", { method: "POST", body: JSON.stringify({ phone: v, lang: S.lang }) });
    if (r.ok) { const j = await r.json(); S.masked = j.to; S.demo = j.demo_otp || ""; S.view = "otp"; return render(); }
    if (r.status === 401) ex(); else S.err = r.status === 422 ? t("phBad") : r.status === 429 ? t("phWait") : t("phFail");
  } catch { S.err = t("net"); }
  render();
}
async function phVerify() {
  const c = $("#otp").value.trim(); S.err = "";
  if (!/^\d{6}$/.test(c)) { S.err = t("otFmt"); return render(); }
  try {
    const r = await authed("/farmer/phone/verify", { method: "POST", body: JSON.stringify({ code: c }) });
    if (r.ok) { S.view = "boot"; await load(); return toast(t("phOk", { n: S.masked || "" })); }
    if (r.status === 401) ex(); else { const d = (await r.json().catch(() => ({}))).detail || ""; S.err = r.status === 429 ? t("otMany") : r.status === 422 ? t("otFmt") : /expired/i.test(d) ? t("otOld") : t("otBad"); }
  } catch { S.err = t("net"); }
  render();
}
async function phRemove() {
  if (!confirm(t("phRmQ"))) return;
  try {
    const r = await authed("/farmer/phone", { method: "DELETE" });
    if (r.status === 401) { ex(); return render(); }
    if (r.ok) { S.card.phone = { registered: false, masked: null }; localStorage.card = JSON.stringify(S.card); localStorage[skipKey()] = Date.now(); render(); toast(t("phOff")); }
  } catch { toast(t("net")); }
}
// ---- Asking the FPO for a change. The farmer types (or fills a form); the server works out the new numbers, the
// farmer confirms, and the FPO decides. Nothing here changes the plan: the card only changes when the FPO approves.
const FLD = { qty_kg: "fQty", ready_hr: "fReady", deadline_hr: "fDead" };
const ECODE = { empty: "e0", twice: "e1", qty_range: "e2", ready_neg: "e3", deadline_max: "e4", order: "e5", same: "e6" };
const RSN = { too_late: "r1", not_possible: "r2", capacity: "r3", other: "r4" };
const STW = { pending: "sP", approved: "sA", rejected: "sR", withdrawn: "sW", expired: "sE" };
const chatInit = () => ({ msgs: [], text: "", busy: false, draft: null, form: false, reqs: null, f: { field: "qty_kg", how: "set", v: "" }, focus: true });
const CH = () => S.chat || (S.chat = chatInit());
const chatOk = () => !!(S.token && S.card && S.online && S.view === "card");
function fab() {   // the round button, bottom right, on the card screen only (it needs the server)
  const b = $("#fab"), on = chatOk(); b.hidden = !on; document.body.classList.toggle("hasfab", on);
  if (on) { b.innerHTML = ic("chat"); b.setAttribute("aria-label", t("chat")); b.title = t("chat"); }
}
function chatFocus() { const C = S.chat; if (S.view !== "chat" || !C || !C.focus) return; C.focus = false; const el = $("#cq"); if (el) el.focus(); }
const lineTxt = l => t(FLD[l.field]) + ": " + (l.field === "qty_kg" ? esc(l.from) + " \u2192 " + esc(l.to) : esc(tshow(l.from)) + " \u2192 " + esc(tshow(l.to)));
const mtext = m => esc(m.k ? t(m.k, m.v) : m.text);
function chatView() {
  const C = CH(), f = C.f, time = f.field !== "qty_kg", d = C.draft;
  const bub = m => `<div style="align-self:${m.me ? "flex-end" : "flex-start"};max-width:90%;padding:12px 14px;border-radius:14px;${m.me ? "background:#1E4D3A;color:#fff" : "background:#F2F6F3"}">${mtext(m)}</div>`;
  const opt = (v, k, cur) => `<option value="${v}"${v === cur ? " selected" : ""}>${t(k)}</option>`;
  const hk = time ? { set: "hTs", more: "hTm", less: "hTl" } : { set: "hQs", more: "hQm", less: "hQl" };
  const bottom = C.busy ? `<div class="note" role="status" style="font-size:17px">${t("cBusy")}</div>`
    : d ? `<section class="slip" style="padding-top:12px"><b>${t("cUnd")}</b>${d.lines.map(l => `<div style="padding-top:10px;font-size:20px">${lineTxt(l)}</div>`).join("")}</section>${btn("cYes", t("cYes"), "green")}${btn("cNo", t("cNo"), "line")}`
    : C.form ? `<label>${t("cFld")}<select id="cf">${Object.keys(FLD).map(k => opt(k, FLD[k], f.field)).join("")}</select></label>
      <label>${t("cHow")}<select id="ch">${["set", "more", "less"].map(k => opt(k, hk[k], f.how)).join("")}</select></label>
      <label>${t("cVal")}<input id="cv" type="${time && f.how === "set" ? "time" : "number"}" inputmode="decimal" step="any" min="0" value="${esc(f.v)}" style="letter-spacing:0"></label>
      ${btn("cFormSend", t("cSend"), "green")}<button class="link" data-act="cTxtOn">${t("cTxt")}</button>`
    : `<label><span class="note" style="font-size:16px">${t("cHint")}</span><input id="cq" value="${esc(C.text)}" placeholder="${esc(t("cPh"))}" maxlength="300" autocomplete="off" style="letter-spacing:0;font-size:19px"></label>
      ${btn("cSend", t("cSend"), "green")}<button class="link" data-act="cFormOn">${t("cForm")}</button>`;
  const rs_ = (C.reqs || []).filter(r => r.status !== "draft");
  const reqs = !rs_.length ? "" : `<h2 style="font-size:22px;margin:8px 0 0">${t("cMine")}</h2>` + rs_.map(r => `<section class="slip" style="padding-top:10px">
      <div><b>${t(STW[r.status] || "cFail")}</b>${r.status === "rejected" && RSN[r.reason_code] ? ": " + t(RSN[r.reason_code]) : ""}</div>
      ${r.changes.map(l => `<div style="padding-top:6px">${lineTxt(l)}</div>`).join("")}
      ${r.status === "pending" ? `<button class="link" data-act="cWd" data-id="${r.id}">${t("cWd")}</button>` : ""}</section>`).join("");
  return `<div class="body"><div class="row"><button class="link" data-act="home">\u2039 ${t("back")}</button>${langBar()}</div>
    <h1 class="mid" style="font-size:30px">${t("cTitle")}</h1>
    <div class="col" style="gap:10px;align-items:stretch" aria-live="polite">${C.msgs.map(bub).join("")}</div>${bottom}${reqs}</div>`;
}
// One call to the backend with the farmer's token; null when the phone cannot reach it.
async function cApi(path, method, body) {
  try {
    const r = await authed(path, method === "POST" ? { method, body: body === undefined ? undefined : JSON.stringify(body) } : {});
    S.online = true; return { r, j: await r.json().catch(() => ({})) };
  } catch { return null; }
}
const cFail = (C, x) => { if (x && x.r.status === 401) { ex(); return render(); }
  C.msgs.push({ k: !x ? "net" : x.r.status === 429 ? "cMany" : x.r.status === 409 ? "cClosed" : "cFail" }); render(); };
async function chatReqs() {
  const x = await cApi("/farmer/requests");
  if (x && x.r.status === 401) { ex(); return render(); }
  if (x && x.r.ok && S.chat) S.chat.reqs = x.j.requests;
  if (S.view === "chat") render();
}
async function cChat(body) {   // text or form -> either a card to confirm, a question, a refusal, or "use the form"
  const C = CH(); C.busy = true; render();
  const x = await cApi("/farmer/chat", "POST", body); C.busy = false; C.focus = true;
  if (!x || !x.r.ok) return cFail(C, x);
  const j = x.j;
  if (j.status === "confirm") { C.draft = { id: j.request_id, lines: j.changes }; C.focus = false; }
  else if (j.status === "llm_unavailable") { C.form = true; C.focus = false; C.msgs.push({ k: "cLlm" }); }
  else if (j.status === "clarify") C.msgs.push(j.code === "empty" ? { k: "e0" } : { text: j.message });
  else C.msgs.push(ECODE[j.code] ? { k: ECODE[j.code], v: { m: (j.params || {}).max } } : { text: j.message || "" });
  render();
}
function cSend() {
  const C = CH(), q = ($("#cq") ? $("#cq").value : C.text).trim(); if (!q || C.busy) return;
  C.msgs.push({ me: 1, text: q }); C.text = ""; return cChat({ message: q });
}
function cFormSend() {
  const C = CH(), f = C.f; if (C.busy) return; let v;
  if (f.field !== "qty_kg" && f.how === "set") { const m = /^(\d{1,2}):(\d{2})$/.exec(f.v); v = m ? +m[1] + +m[2] / 60 : NaN; }
  else v = parseFloat(String(f.v).replace(",", "."));
  if (!isFinite(v) || (f.how !== "set" && v < 0)) { C.msgs.push({ k: "e0" }); return render(); }
  return cChat({ structured: { changes: [{ field: f.field, mode: f.how === "set" ? "set" : "shift", value: f.how === "less" ? -v : v }] } });
}
async function cYes() {
  const C = CH(); if (!C.draft || C.busy) return; C.busy = true; render();
  const x = await cApi(`/farmer/requests/${C.draft.id}/confirm`, "POST"); C.busy = false; C.draft = null;
  if (x && x.r.ok) { C.msgs.push({ k: "cSent" }); C.focus = false; render(); return chatReqs(); }
  if (x && x.r.status === 409) { C.msgs.push({ k: /closed/i.test(x.j.detail || "") ? "cClosed" : "cStale" }); C.focus = true; return render(); }
  cFail(C, x);
}
function cNo() {
  const C = CH(), id = C.draft && C.draft.id; C.draft = null; C.focus = true; render();
  if (id) cApi(`/farmer/requests/${id}/withdraw`, "POST");   // tidy up the unsent draft; nothing waits on the answer
}
async function cWd(a) {
  const id = +a.dataset.id; if (!id) return;
  const x = await cApi(`/farmer/requests/${id}/withdraw`, "POST");
  if (x && x.r.status === 401) { ex(); return render(); }
  chatReqs();
}
const CHAT = { chat() { hush(); const C = CH(); C.focus = true; S.err = ""; S.view = "chat"; render(); chatReqs(); },
  cSend, cFormSend, cYes, cNo, cWd, cFormOn() { CH().form = true; render(); }, cTxtOn() { const C = CH(); C.form = false; C.focus = true; render(); } };
document.addEventListener("input", e => { const C = S.chat; if (!C) return; if (e.target.id === "cq") C.text = e.target.value; else if (e.target.id === "cv") C.f.v = e.target.value; });
document.addEventListener("change", e => {   // the form's drop-downs change what kind of value the box takes
  const C = S.chat, id = e.target.id; if (!C || (id !== "cf" && id !== "ch")) return;
  if (id === "cf") C.f.field = e.target.value; else C.f.how = e.target.value; C.f.v = ""; render();
});
const ACT = { ...CHAT, login, login0() { S.view = "login"; render(); }, home() { hush(); S.view = "card"; render(); }, slip() { hush(); S.view = "slip"; render(); }, quote() { hush(); S.view = "quote"; render(); },
  listen: speak, install() { if (!deferred) return; deferred.prompt(); deferred.userChoice.catch(() => {}).then(() => { deferred = null; render(); }); }, refresh: load, phSend, phVerify, phRm: phRemove, phSkip() { localStorage[skipKey()] = Date.now(); S.err = ""; S.view = "card"; render(); }, phAdd() { S.err = ""; S.view = "phone"; render(); }, phChg() { S.err = ""; S.view = "phone"; render(); }, logout() { hush(); clear(); S.view = "login"; render(); } };
document.addEventListener("click", e => {
  const l = e.target.closest("[data-lang]"); if (l) { S.lang = localStorage.lang = l.dataset.lang; hush(); return render(); }
  const a = e.target.closest("[data-act]"); if (a) ACT[a.dataset.act](a);
});
if ("serviceWorker" in navigator) {   // new version found: reload by itself, or ask first if the farmer is typing
  const had = !!navigator.serviceWorker.controller; let going = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (!had || going) return; going = true; if (typing()) { toast(t("newVer")); toast.reload = true; } else location.reload(); });
  navigator.serviceWorker.register("sw.js").then(reg => { const chk = () => reg.update().catch(() => {}); document.addEventListener("visibilitychange", () => { if (!document.hidden) chk(); }); addEventListener("online", chk); }).catch(() => {});
}
document.addEventListener("click", e => { if (e.target.closest("#sp") && toast.reload) location.reload(); });
document.addEventListener("keydown", e => { if (e.key !== "Enter") return; if (e.target.id === "fid") { e.preventDefault(); $("#pin").focus(); } else if (e.target.id === "pin") login(); else if (e.target.id === "ph") phSend(); else if (e.target.id === "otp") phVerify(); else if (e.target.id === "cq") cSend(); else if (e.target.id === "cv") cFormSend(); });
addEventListener("online", () => S.token && load());
if (S.token) { S.view = S.card ? "card" : "boot"; if (S.card) render(); load(); } else { S.view = "login"; render(); }
