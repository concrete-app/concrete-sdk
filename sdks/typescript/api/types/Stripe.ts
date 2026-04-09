// Source of truth: api/openapi.yaml — Products, Prices, Coupons schemas

export type StripeEnv = "beta" | "prod";

export const Products = {
  beta: {
    DEVELOPER:                    "prod_UIWeQ2wZRIymNt",
    PROJECTROOM:                  "prod_UIWbVvYWUIO9rS",
    CHATINTEGRATION_STARTER:      "prod_UIWeNAcbEB6cpU",
    CHATINTEGRATION_PROFESSIONAL: "prod_UIWe1y22cGjtBc",
    ADD_ON_200GB:                 "prod_UIWdxTmTrPqyCf",
    ADD_ON_500GB:                 "prod_UIWdJe6Y1AaXwq",
    ADD_ON_1TB:                   "prod_UIWcK0RJvGV4Qw",
    CHAT_AGENT:                   "prod_UIWfac6b2jgkQO",
    KNOWLEDGE_BASE_PROJECT:       "prod_UIWf6dnMQOKg22",
  },
  prod: {
    DEVELOPER:                    "prod_UBhelBG3P9qpj5",
    PROJECTROOM:                  "prod_UGc67PC09uMYuh",
    CHATINTEGRATION_STARTER:      "prod_UGbRoO3FIGzPEl",
    CHATINTEGRATION_PROFESSIONAL: "prod_UGbRxts1OXtMJR",
    ADD_ON_200GB:                 "prod_UGbydQqsDQRq9o",
    ADD_ON_500GB:                 "prod_UGbzEwRzrMBkMq",
    ADD_ON_1TB:                   "prod_UGc0o1j6kjrMBR",
    CHAT_AGENT:                   "prod_TSYpaQ8bCYpBJH",
    KNOWLEDGE_BASE_PROJECT:       "prod_U6SOp9rhsrqlyd",
  },
} as const;

export const Prices = {
  beta: {
    DEVELOPER:                    "price_1TJvbXE2PhgH7BCtUmsdORBX",
    PROJECTROOM:                  "price_1TJvYlE2PhgH7BCtZEs9qEKn",
    CHATINTEGRATION_STARTER:      "price_1TJvbJE2PhgH7BCtgrFk6Jnv",
    CHATINTEGRATION_PROFESSIONAL: "price_1TJvaxE2PhgH7BCtzt2ZIR4n",
    ADD_ON_200GB:                 "price_1TJvaPE2PhgH7BCtCJlEPwMQ",
    ADD_ON_500GB:                 "price_1TJvZsE2PhgH7BCth7NGdvSX",
    ADD_ON_1TB:                   "price_1TJvZRE2PhgH7BCtGMDiF43e",
    CHAT_AGENT:                   "price_1TJvccE2PhgH7BCtwkEn8m6x",
    KNOWLEDGE_BASE_PROJECT:       "price_1TJvbuE2PhgH7BCtORwUFzCi",
  },
  prod: {
    DEVELOPER:                    "price_1TDKEsCjm4ij4OwQxrx6Mhxw",
    PROJECTROOM:                  "price_1TI4sICjm4ij4OwQTyAejxsY",
    CHATINTEGRATION_STARTER:      "price_1TI4EACjm4ij4OwQZD6BETcr",
    CHATINTEGRATION_PROFESSIONAL: "price_1TI4EzCjm4ij4OwQvrLAggXc",
    ADD_ON_200GB:                 "price_1TI4krCjm4ij4OwQ9Ni6W9Wp",
    ADD_ON_500GB:                 "price_1TI4laCjm4ij4OwQAlhNEjlW",
    ADD_ON_1TB:                   "price_1TI4m5Cjm4ij4OwQL7mDF5ft",
    CHAT_AGENT:                   "price_1SVdi0Cjm4ij4OwQwDaVRuQc",
    KNOWLEDGE_BASE_PROJECT:       "price_1T8FTmCjm4ij4OwQy5g9Yyl7",
  },
} as const;

export const Coupons = {
  beta: {
    NEWCOPYSTORE:     "promo_1TKCbfE2PhgH7BCt232UFVMF",
    PROJECTROOM:      "promo_1TK1xfE2PhgH7BCtRCs7ZPPB",
    TESTER_12_MONTHS: "adiENO5W",
  },
  prod: {
    NEWCOPYSTORE:     "promo_1T9RpqCjm4ij4OwQkyJpNJDw",
    PROJECTROOM:      "promo_1TK1yWCjm4ij4OwQQzPUJXGV",
    TESTER_12_MONTHS: "adiENO5W",
  },
} as const;
