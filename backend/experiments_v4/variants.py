"""Variant definitions (env switches). Every variant runs on identical (family, n, seed, road matrix)."""
CW5 = {"ILO_CW_LAMBDAS": "0.6,0.8,1.0,1.2,1.5"}
ENR = {"ILO_ENRICH": 1}
C1 = {"ILO_KEEP_ORDER": 1}
C3 = {"ILO_SIM_SPOIL": 1}
C2 = {"ILO_BOTH_DIRS": 1}
VARIANTS = {
    "V0_zip":          {},
    "V1_cw5+enrich":   {**CW5, **ENR},                       # reconstruction of the prior session's change
    "C1_keeporder":    {**C1},
    "C3_simspoil":     {**C3},
    "C13":             {**C1, **C3},
    "C123":            {**C1, **C2, **C3},
    "C13+V1":          {**C1, **C3, **CW5, **ENR},
    "C13+CG2":         {**C1, **C3, "ILO_COLGEN": 2},
    "C13+CG2+V1":      {**C1, **C3, **CW5, **ENR, "ILO_COLGEN": 2},
    "TL120":           {"ILO_SP_TIME_LIMIT": 120},
    "C13+TL120":       {**C1, **C3, "ILO_SP_TIME_LIMIT": 120},
    "knn_forced":      {"ILO_CW_ALL_PAIRS_MAX": 30},          # CW restricted to 25-NN pairs (tests the >400 branch)
    "C13+knn_forced":  {**C1, **C3, "ILO_CW_ALL_PAIRS_MAX": 30},
    "V0@T0":           {"TURNAROUND": 0.0},
    "V0@T2.5":         {"TURNAROUND": 2.5},
    "BEST@T0":         {**C1, **C3, **CW5, **ENR, "ILO_COLGEN": 2, "TURNAROUND": 0.0},
    "BEST@T2.5":       {**C1, **C3, **CW5, **ENR, "ILO_COLGEN": 2, "TURNAROUND": 2.5},
    "BEST":            {**C1, **C3, **CW5, **ENR, "ILO_COLGEN": 2},
    "BEST+TL120":      {**C1, **C3, **CW5, **ENR, "ILO_COLGEN": 2, "ILO_SP_TIME_LIMIT": 120},
    "BEST+knn":        {**C1, **C3, **CW5, **ENR, "ILO_COLGEN": 2, "ILO_CW_ALL_PAIRS_MAX": 30},
}
