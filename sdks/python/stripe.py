# Source of truth: api/openapi.yaml — mirrors TypeScript Stripe.ts Products/Prices/Coupons

from typing import Dict, Literal

StripeEnv = Literal["beta", "prod"]

Products: Dict[StripeEnv, Dict[str, str]] = {
    "beta": {
        "Developer":                   "prod_UIWeQ2wZRIymNt",
        "Projectroom":                 "prod_UIWbVvYWUIO9rS",
        "ChatintegrationStarter":      "prod_UIWeNAcbEB6cpU",
        "ChatintegrationProfessional": "prod_UIWe1y22cGjtBc",
        "AddOn200Gb":                  "prod_UIWdxTmTrPqyCf",
        "AddOn500Gb":                  "prod_UIWdJe6Y1AaXwq",
        "AddOn1Tb":                    "prod_UIWcK0RJvGV4Qw",
        "ChatAgent":                   "prod_UIWfac6b2jgkQO",
        "KnowledgeBaseProject":        "prod_UIWf6dnMQOKg22",
        "Lernmedien":                  "prod_ULoucf3hhqGwPk",
    },
    "prod": {
        "Developer":                   "prod_UBhelBG3P9qpj5",
        "Projectroom":                 "prod_UGc67PC09uMYuh",
        "ChatintegrationStarter":      "prod_UGbRoO3FIGzPEl",
        "ChatintegrationProfessional": "prod_UGbRxts1OXtMJR",
        "AddOn200Gb":                  "prod_UGbydQqsDQRq9o",
        "AddOn500Gb":                  "prod_UGbzEwRzrMBkMq",
        "AddOn1Tb":                    "prod_UGc0o1j6kjrMBR",
        "ChatAgent":                   "prod_TSYpaQ8bCYpBJH",
        "KnowledgeBaseProject":        "prod_U6SOp9rhsrqlyd",
        "Lernmedien":                  "prod_ULotwqdgr3hjWJ",
    },
}

Prices: Dict[StripeEnv, Dict[str, str]] = {
    "beta": {
        "Developer":                   "price_1TJvbXE2PhgH7BCtUmsdORBX",
        "Projectroom":                 "price_1TJvYlE2PhgH7BCtZEs9qEKn",
        "ChatintegrationStarter":      "price_1TJvbJE2PhgH7BCtgrFk6Jnv",
        "ChatintegrationProfessional": "price_1TJvaxE2PhgH7BCtzt2ZIR4n",
        "AddOn200Gb":                  "price_1TJvaPE2PhgH7BCtCJlEPwMQ",
        "AddOn500Gb":                  "price_1TJvZsE2PhgH7BCth7NGdvSX",
        "AddOn1Tb":                    "price_1TJvZRE2PhgH7BCtGMDiF43e",
        "ChatAgent":                   "price_1TJvccE2PhgH7BCtwkEn8m6x",
        "KnowledgeBaseProject":        "price_1TJvbuE2PhgH7BCtORwUFzCi",
    },
    "prod": {
        "Developer":                   "price_1TDKEsCjm4ij4OwQxrx6Mhxw",
        "Projectroom":                 "price_1TI4sICjm4ij4OwQTyAejxsY",
        "ChatintegrationStarter":      "price_1TI4EACjm4ij4OwQZD6BETcr",
        "ChatintegrationProfessional": "price_1TI4EzCjm4ij4OwQvrLAggXc",
        "AddOn200Gb":                  "price_1TI4krCjm4ij4OwQ9Ni6W9Wp",
        "AddOn500Gb":                  "price_1TI4laCjm4ij4OwQAlhNEjlW",
        "AddOn1Tb":                    "price_1TI4m5Cjm4ij4OwQL7mDF5ft",
        "ChatAgent":                   "price_1SVdi0Cjm4ij4OwQwDaVRuQc",
        "KnowledgeBaseProject":        "price_1T8FTmCjm4ij4OwQy5g9Yyl7",
    },
}

Coupons: Dict[StripeEnv, Dict[str, str]] = {
    "beta": {
        "Newcopystore":    "promo_1TKCbfE2PhgH7BCt232UFVMF",
        "Projectroom":     "promo_1TK1xfE2PhgH7BCtRCs7ZPPB",
        "Tester12Months":  "adiENO5W",
    },
    "prod": {
        "Newcopystore":    "promo_1T9RpqCjm4ij4OwQkyJpNJDw",
        "Projectroom":     "promo_1TK1yWCjm4ij4OwQQzPUJXGV",
        "Tester12Months":  "adiENO5W",
    },
}
