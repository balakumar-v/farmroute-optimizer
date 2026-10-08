import sys, copy
sys.path.insert(0,'.')
import ilo_v3 as I, baselines_v3 as B
from stress import monte_carlo_stress, withhold_fragile
from logistics_lib_v2 import generate_scenario_v2
agg={}
for seed in range(1,5):
    f,fl,m=generate_scenario_v2(n_farmers=80,n_markets=3,seed=seed)
    prices=B._as_prices(m,B.FARMGATE_DISCOUNT,None)
    res=I.run_ilo_v3(f,copy.deepcopy(fl),m)
    mc_sel=monte_carlo_stress(res,f,fl,m,prices,n_draws=100,seed=100+seed)       # used to select
    for thr in (None,0.7,0.8,0.9):
        out=res if thr is None else withhold_fragile(res,f,mc_sel,thr)[0]
        ev=monte_carlo_stress(out,f,fl,m,prices,n_draws=100,seed=900+seed)        # fresh draws to evaluate
        p=ev["plan"]
        a=agg.setdefault(thr,dict(n=0,trips=0,nom=0,mean=0,p5=0,pneg=0,es=0,lost=0))
        a["n"]+=1; a["trips"]+=p.get("trips",0)
        for k,kk in (("nom","nominal_gain"),("mean","mean_gain"),("p5","p5_gain"),("pneg","prob_gain_negative"),("es","expected_shortfall_5pct"),("lost","mean_trips_lost")):
            a[k]+=p.get(kk,0)
    print(seed,"done",flush=True)
print("threshold  trips  nominal   mean_gain   p5_gain  P(gain<0)  ES5%   trips_lost/draw   (sums over 4 seeds; P and lost averaged)")
for thr,a in agg.items():
    print("%-9s %5d %9d %10d %9d  %.3f %8d   %.2f"%(thr,a["trips"],a["nom"],a["mean"],a["p5"],a["pneg"]/a["n"],a["es"],a["lost"]/a["n"]))
