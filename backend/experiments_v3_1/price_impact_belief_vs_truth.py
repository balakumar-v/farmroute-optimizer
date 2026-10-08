import sys, copy, time
sys.path.insert(0,'.')
import ilo_v3 as I, baselines_v3 as B
from price_impact import PriceImpact
from logistics_lib_v2 import generate_scenario_v2
TRUTHS=(1.0,3.5)
planners=[("ignorant",None),("0.5x truth",0.5),("exact",1.0),("2x truth",2.0)]
tot={}
for seed in range(1,4):
    f,fl,m = generate_scenario_v2(n_farmers=80, n_markets=3, seed=seed)
    prices=B._as_prices(m,B.FARMGATE_DISCOUNT,None)
    fgsum=sum(prices.value_of([x]) for x in f)
    for T in TRUTHS:
        truth=PriceImpact(scale=T)
        for name,mult in planners:
            t=time.time()
            belief=None if mult is None else PriceImpact(scale=T*mult)
            res,meta=I.run_ilo_v3(f,copy.deepcopy(fl),m,safeguard=False,price_impact=belief,true_price_impact=truth,return_meta=True)
            g=meta["final_value"]-fgsum
            d=[r for r in res if r["vehicle_id"] is not None]
            v=tot.setdefault((T,name),[0.0,0,0.0]); v[0]+=g; v[1]+=len(d); v[2]+=sum(r["total_qty_kg"] for r in d)
            print(seed,"truth x%.1f"%T,name,round(g),len(d),round(sum(r["total_qty_kg"] for r in d)),meta["chosen"],round(time.time()-t),flush=True)
print("RESULT: gain vs farm-gate under TRUE price impact (3 seeds, n=80)")
for (T,name),v in tot.items(): print("truth x%.1f  planner %-11s gain %7d  trips %3d  kg hauled %6d"%(T,name,v[0],v[1],v[2]))
