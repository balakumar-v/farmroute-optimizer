import sys, copy, time
sys.path.insert(0,'.')
from logistics_lib_v2 import generate_scenario_v2
import ilo_v3 as I
print("n  fleet  seed | fg_only  old_final  new_final  | new vs old %  | B(aware) B0(blind) A | trips hints sec")
for n,frac in ((150,0.5),(300,1.0),(600,1.0),(1000,1.0)):
    tot_old=tot_new=tot_fg=0
    for seed in (1,2):
        f,fl,m = generate_scenario_v2(n_farmers=n, n_markets=max(3,n//300+2), seed=seed)
        fl=fl[:max(1,int(len(fl)*frac))]
        r0,m0 = I.run_ilo_v3(f,copy.deepcopy(fl),m,return_meta=True,fleet_aware=False)
        t=time.time()
        r1,m1 = I.run_ilo_v3(f,copy.deepcopy(fl),m,return_meta=True,fleet_aware=True)
        dt=time.time()-t
        pv=m1["plan_values"]; fa=m1["fleet_aware"]
        fg=pv["fallback:farm_gate_only"]
        tot_old+=m0["final_value"]; tot_new+=m1["final_value"]; tot_fg+=fg
        print(n,len(fl),seed,"|",round(fg),round(m0["final_value"]),round(m1["final_value"]),"|",
              "%.2f"%(100*(m1["final_value"]/m0["final_value"]-1)),"|",
              round(pv.get("B:set_partition",0)),round(pv.get("B0:set_partition_fleet_blind",0)),round(pv["A:ilo_pools"]),
              "|",fa.get("trips_chosen"),fa.get("hints_placed"),fa.get("status"),round(dt,1),m1["chosen"],flush=True)
    print("  => n",n,"fleet",frac,"gain over farmgate: old %.2f%% new %.2f%%"%(100*(tot_old/tot_fg-1),100*(tot_new/tot_fg-1)),flush=True)
