import sys, copy
sys.path.insert(0,'.')
import ilo_v3 as I
from logistics_lib_v2 import generate_scenario_v2
TR=(0.05,0.10,0.15,0.20,0.25,0.30,0.35)
agg={}
for seed in range(1,7):
    f,fl,m=generate_scenario_v2(n_farmers=80,n_markets=3,seed=seed)
    for da in (0.10,0.20,0.30):
        res,meta=I.run_ilo_v3(f,copy.deepcopy(fl),m,discount=da,safeguard=False,return_meta=True,stress_discounts=TR)
        for d,v in meta["discount_stress"].items():
            a=agg.setdefault((da,d),[0,0,0,0]); a[0]+=v["gain_dispatch_all"]; a[1]+=v["gain_with_quote_rule"]; a[2]+=v["trips_losing"]; a[3]+=v["trips"]
        print(seed,da,"done",flush=True)
print("planner-assumed d | truth d: gain_all  gain_with_quote_rule  trips_losing/trips")
for da in (0.10,0.20,0.30):
    for d in TR:
        a=agg[(da,d)]; print("assumed %.2f truth %.2f  %8d %8d   %d/%d"%(da,d,a[0],a[1],a[2],a[3]))
    print("assumed %.2f MEAN over truths: all %d  rule %d"%(da,sum(agg[(da,d)][0] for d in TR)/len(TR),sum(agg[(da,d)][1] for d in TR)/len(TR)))
