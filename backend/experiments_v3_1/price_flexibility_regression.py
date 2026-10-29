import pandas as pd, numpy as np, glob
def load(f):
    d=pd.read_csv(f)
    d=d[(d.unit_name_price=="Rs./Quintal")&(d.unit_name_arrival=="Metric Tonnes")]
    d=d[(d.model_price>0)&(d.arrival_qty>0)].copy()
    d["lp"]=np.log(d.model_price); d["la"]=np.log(d.arrival_qty)
    return d
def within(d, cols=("market_name","crop"), date=True, iters=8):
    y=d.lp.values.copy(); x=d.la.values.copy()
    g1=d.groupby(list(cols)).ngroup().values
    g2=d.groupby(["crop","arrival_date"]).ngroup().values if date else None
    for _ in range(iters):
        for g in ([g1,g2] if date else [g1]):
            for v in (y,x):
                m=pd.Series(v).groupby(g).transform("mean").values; v-=m
    b=(x*y).sum()/(x*x).sum(); n=len(y)
    res=y-b*x; se=np.sqrt((res**2).sum()/(n-1)/(x*x).sum())
    return b,se,n
for f in sorted(glob.glob("data/raw/*.csv")):
    d=load(f)
    # keep mandi-crops with >=15 obs
    k=d.groupby(["market_name","crop"]).arrival_date.transform("count"); d=d[k>=15]
    out=[]
    for crop,dc in d.groupby("crop"):
        if len(dc)<150: continue
        b0,se0,n=within(dc,date=False); b1,se1,_=within(dc,date=True)
        out.append((crop,n,round(b0,3),round(se0,3),round(b1,3),round(se1,3)))
    print(f.split("_")[2], "all:",[round(x,3) for x in within(d,date=False)[:2]],[round(x,3) for x in within(d,date=True)[:2]])
    for o in out: print("   crop,n,b_mktFE,se,b_mktFE+dateFE,se:",o)
