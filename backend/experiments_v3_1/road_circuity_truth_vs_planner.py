import sys, copy
sys.path.insert(0,'.')
import logistics_lib_v2 as L, algorithms_v2 as A, baselines_v3 as B, ilo_v3 as I
from logistics_lib_v2 import generate_scenario_v2
TRUTH=1.4
plan_k=(1.0,1.2,1.4,1.6)
tot={k:[0,0,0.0,0] for k in plan_k}
for seed in range(1,7):
    f,fl,m = generate_scenario_v2(n_farmers=80, n_markets=3, seed=seed)
    by={x.id:x for x in f}
    for k in plan_k:
        with L.road_circuity(k):
            res = I.run_ilo_v3(f,copy.deepcopy(fl),m)
        pools=[[by[i] for i in r["farmer_ids"]] for r in res if r["vehicle_id"] is not None]
        with L.road_circuity(TRUTH):
            prices=B._as_prices(m,B.FARMGATE_DISCOUNT,None)
            out=A.run_our_system_v2(f,copy.deepcopy(fl),m,raw_pools_override=pools,withhold_uneconomic=False,
                fix_route_duration=True,spoilage_from_pickup=True,charge_return_leg=True)
            disp=loss=0; gain=0.0; noveh=0
            for r in out:
                if r["vehicle_id"] is None: noveh+=1; continue
                disp+=1
                d=r["net_return"]-prices.value_of([by[i] for i in r["farmer_ids"]]); gain+=d
                if d<0: loss+=1
        t=tot[k]; t[0]+=disp; t[1]+=loss; t[2]+=gain; t[3]+=noveh
        print(seed,k,disp,loss,round(gain),noveh,flush=True)
print("TRUTH circuity",TRUTH)
for k,v in tot.items(): print("planner k=%.1f trips %d below_farmgate %d infeasible_under_truth %d  gain_vs_farmgate(true roads) %d"%(k,v[0],v[1],v[3],v[2]))
