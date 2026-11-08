import time, copy, sys
sys.path.insert(0,'.')
from logistics_lib_v2 import generate_scenario_v2
from ilo_v3 import run_ilo_v3
for n in (60,150,300,600,1000):
    f,fl,m = generate_scenario_v2(n_farmers=n, n_markets=max(3,n//300+2), seed=1)
    t=time.time()
    res,meta = run_ilo_v3(f,fl,m,return_meta=True)
    dt=time.time()-t
    c=meta.get("candidates",{})
    pv=meta["plan_values"]
    print(n, "fleet",len(fl),"sec",round(dt,1),"chosen",meta["chosen"],"final",round(meta["final_value"]),
          {k:round(v) for k,v in pv.items()}, "sp_trips",c.get("sp_trips_chosen"),"cands",c.get("total_kept"),
          "dropped",meta.get("trips_dropped_below_farmgate"), "worse_prorata", meta.get("farmers_worse_off_under_prorata_split"),
          "dispatched", sum(1 for r in res if r["vehicle_id"] is not None), "unserved_kg", round(sum(r.get("unserved_no_vehicle_kg",0) for r in res)), flush=True)
