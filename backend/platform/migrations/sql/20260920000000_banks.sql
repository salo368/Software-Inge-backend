-- Banks + bank_rates. Rates depend on (bank, term_days, amount range).
-- Rate lookup: highest min_amount for (bank_id, term_days) such that min_amount <= amount.
-- Seed picks tasas variadas para que segun (monto, plazo) gane distinto banco.

-- +migrate up

CREATE TABLE banks (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    code         VARCHAR(50)   NOT NULL UNIQUE,
    name         VARCHAR(120)  NOT NULL,
    logo_key     TEXT          NOT NULL,
    description  TEXT          NOT NULL,
    tier         VARCHAR(10)   NOT NULL,
    rating_by    VARCHAR(80)   NOT NULL,
    min_amount   NUMERIC(15,2) NOT NULL,
    highlights   TEXT[]        NOT NULL DEFAULT '{}',
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE bank_rates (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_id     UUID          NOT NULL REFERENCES banks(id) ON DELETE CASCADE,
    term_days   INT           NOT NULL,
    min_amount  NUMERIC(15,2) NOT NULL,
    rate        NUMERIC(5,2)  NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (bank_id, term_days, min_amount)
);

CREATE INDEX bank_rates_lookup_idx ON bank_rates (bank_id, term_days, min_amount DESC);

-- Banks seed.
INSERT INTO banks (code, name, logo_key, description, tier, rating_by, min_amount, highlights) VALUES
('bancolombia',     'Bancolombia',           'banks/bancolombia.png',     'El banco mas grande de Colombia. Cobertura nacional y app lider.',                            'AAA', 'Fitch Ratings',   500000,   ARRAY['La red mas grande del pais', 'App lider en Colombia', 'Atencion 24/7']),
('davivienda',      'Davivienda',            'banks/davivienda.png',      'Banco solido, especialmente competitivo en plazos largos. Ecosistema DaviPlata.',            'AAA', 'BRC Ratings',     500000,   ARRAY['Fuerte en plazos largos', 'Ecosistema DaviPlata', 'Renovacion automatica']),
('bbva',            'BBVA',                  'banks/bbva.png',            'Respaldo internacional espanol. Banca movil premiada.',                                       'AAA', 'Fitch Ratings',   500000,   ARRAY['Respaldo internacional', 'Banca movil premiada', 'Tasas estables']),
('bogota',          'Banco de Bogota',       'banks/bogota.png',          'Banco tradicional del Grupo Aval, fundado en 1870.',                                          'AAA', 'BRC Ratings',     500000,   ARRAY['Tradicion desde 1870', 'Grupo Aval', 'Cobertura nacional']),
('itau',            'Itau',                  'banks/itau.png',            'El banco mas grande de Latinoamerica. Equilibrio entre tasa y solidez.',                      'AAA', 'Fitch Ratings',   500000,   ARRAY['El banco mas grande de Latam', 'Equilibrio tasa-solidez']),
('scotiabank',      'Scotiabank Colpatria',  'banks/scotiabank.png',      'Presencia en 25 paises. Muy competitivo en plazos largos.',                                   'AAA', 'Fitch Ratings',   500000,   ARRAY['Presencia en 25 paises', 'Mejora en plazos largos']),
('serfinanza',      'Serfinanza',            'banks/serfinanza.png',      'Aliada del Grupo Olimpica. Especialista en plazos largos.',                                   'AA+', 'BRC Ratings',     1000000,  ARRAY['Aliada del Grupo Olimpica', 'Top en plazos largos']),
('pichincha',       'Banco Pichincha',       'banks/pichincha.png',       'Fuerte en corto plazo con apertura 100% en linea.',                                           'AA+', 'BRC Ratings',     1000000,  ARRAY['Campeon del corto plazo', 'Apertura 100% en linea']),
('finandina',       'Banco Finandina',       'banks/finandina.png',       'Banco 100% digital. CDT desde la app en minutos.',                                            'AA+', 'BRC Ratings',     200000,   ARRAY['Banco 100% digital', 'Sin filas ni papeleo', 'CDT desde la app']),
('pibank',          'Pibank',                'banks/pibank.png',          'Neobanco con tasas agresivas. Cero comisiones. Respaldado por Banco Pichincha.',              'AA+', 'Fitch Ratings',   200000,   ARRAY['Tasas agresivas', 'Cero comisiones', 'Respaldado por Banco Pichincha']),
('coltefinanciera', 'Coltefinanciera',       'banks/coltefinanciera.png', 'Especialista en CDTs. Las tasas mas altas del mercado.',                                      'AA',  'BRC Ratings',     2000000,  ARRAY['Las tasas mas altas del mercado', 'Especialista en CDTs']),
('nu',              'Nu Colombia',           'banks/nu.png',              'El neobanco mas grande del mundo. Experiencia 100% digital.',                                 'AA',  'Fitch Ratings',   100000,   ARRAY['El neobanco mas grande del mundo', 'Experiencia 100% digital', 'Sin letra pequena']);

-- Rates seed. 3 rangos por plazo por banco: [0-5M), [5M-50M), [50M+).
-- Tasas variadas para que en distintos (monto, plazo) gane distinto banco.
-- Formato: (code, term_days, min_amount, rate)
WITH r(code, term_days, min_amount, rate) AS (VALUES
    -- Bancolombia (AAA, estable, tasas conservadoras)
    ('bancolombia',    90, 0,        9.30),
    ('bancolombia',    90, 5000000,  9.60),
    ('bancolombia',    90, 50000000, 9.90),
    ('bancolombia',   180, 0,       10.10),
    ('bancolombia',   180, 5000000, 10.40),
    ('bancolombia',   180, 50000000, 10.70),
    ('bancolombia',   360, 0,       11.40),
    ('bancolombia',   360, 5000000, 11.70),
    ('bancolombia',   360, 50000000, 12.10),
    ('bancolombia',   540, 0,       11.60),
    ('bancolombia',   540, 5000000, 11.90),
    ('bancolombia',   540, 50000000, 12.30),
    ('bancolombia',   720, 0,       11.70),
    ('bancolombia',   720, 5000000, 12.00),
    ('bancolombia',   720, 50000000, 12.40),

    -- Davivienda (AAA, fuerte en largos)
    ('davivienda',     90, 0,        8.80),
    ('davivienda',     90, 5000000,  9.10),
    ('davivienda',     90, 50000000, 9.40),
    ('davivienda',    180, 0,        9.90),
    ('davivienda',    180, 5000000, 10.20),
    ('davivienda',    180, 50000000, 10.50),
    ('davivienda',    360, 0,       11.70),
    ('davivienda',    360, 5000000, 12.00),
    ('davivienda',    360, 50000000, 12.40),
    ('davivienda',    540, 0,       12.40),
    ('davivienda',    540, 5000000, 12.70),
    ('davivienda',    540, 50000000, 13.10),
    ('davivienda',    720, 0,       12.90),
    ('davivienda',    720, 5000000, 13.20),
    ('davivienda',    720, 50000000, 13.60),

    -- BBVA (AAA, tasas estables)
    ('bbva',           90, 0,        9.60),
    ('bbva',           90, 5000000,  9.90),
    ('bbva',           90, 50000000, 10.20),
    ('bbva',          180, 0,       10.40),
    ('bbva',          180, 5000000, 10.70),
    ('bbva',          180, 50000000, 11.00),
    ('bbva',          360, 0,       11.60),
    ('bbva',          360, 5000000, 11.90),
    ('bbva',          360, 50000000, 12.20),
    ('bbva',          540, 0,       11.80),
    ('bbva',          540, 5000000, 12.10),
    ('bbva',          540, 50000000, 12.40),
    ('bbva',          720, 0,       11.90),
    ('bbva',          720, 5000000, 12.20),
    ('bbva',          720, 50000000, 12.50),

    -- Banco de Bogota (AAA, similar a BBVA)
    ('bogota',         90, 0,        9.80),
    ('bogota',         90, 5000000, 10.10),
    ('bogota',         90, 50000000, 10.40),
    ('bogota',        180, 0,       10.40),
    ('bogota',        180, 5000000, 10.70),
    ('bogota',        180, 50000000, 11.00),
    ('bogota',        360, 0,       11.50),
    ('bogota',        360, 5000000, 11.80),
    ('bogota',        360, 50000000, 12.10),
    ('bogota',        540, 0,       11.70),
    ('bogota',        540, 5000000, 12.00),
    ('bogota',        540, 50000000, 12.30),
    ('bogota',        720, 0,       11.90),
    ('bogota',        720, 5000000, 12.20),
    ('bogota',        720, 50000000, 12.50),

    -- Itau (AAA, equilibrio)
    ('itau',           90, 0,       10.20),
    ('itau',           90, 5000000, 10.50),
    ('itau',           90, 50000000, 10.80),
    ('itau',          180, 0,       10.90),
    ('itau',          180, 5000000, 11.20),
    ('itau',          180, 50000000, 11.50),
    ('itau',          360, 0,       11.80),
    ('itau',          360, 5000000, 12.10),
    ('itau',          360, 50000000, 12.50),
    ('itau',          540, 0,       12.00),
    ('itau',          540, 5000000, 12.30),
    ('itau',          540, 50000000, 12.70),
    ('itau',          720, 0,       12.10),
    ('itau',          720, 5000000, 12.40),
    ('itau',          720, 50000000, 12.80),

    -- Scotiabank Colpatria (AAA, mejora en largos)
    ('scotiabank',     90, 0,        9.30),
    ('scotiabank',     90, 5000000,  9.60),
    ('scotiabank',     90, 50000000, 9.90),
    ('scotiabank',    180, 0,       10.30),
    ('scotiabank',    180, 5000000, 10.60),
    ('scotiabank',    180, 50000000, 10.90),
    ('scotiabank',    360, 0,       11.80),
    ('scotiabank',    360, 5000000, 12.10),
    ('scotiabank',    360, 50000000, 12.50),
    ('scotiabank',    540, 0,       12.00),
    ('scotiabank',    540, 5000000, 12.30),
    ('scotiabank',    540, 50000000, 12.70),
    ('scotiabank',    720, 0,       12.20),
    ('scotiabank',    720, 5000000, 12.50),
    ('scotiabank',    720, 50000000, 12.90),

    -- Serfinanza (AA+, top en plazos largos)
    ('serfinanza',     90, 1000000, 10.40),
    ('serfinanza',     90, 5000000, 10.70),
    ('serfinanza',     90, 50000000, 11.00),
    ('serfinanza',    180, 1000000, 11.40),
    ('serfinanza',    180, 5000000, 11.70),
    ('serfinanza',    180, 50000000, 12.00),
    ('serfinanza',    360, 1000000, 12.70),
    ('serfinanza',    360, 5000000, 13.00),
    ('serfinanza',    360, 50000000, 13.40),
    ('serfinanza',    540, 1000000, 13.10),
    ('serfinanza',    540, 5000000, 13.40),
    ('serfinanza',    540, 50000000, 13.80),
    ('serfinanza',    720, 1000000, 13.40),
    ('serfinanza',    720, 5000000, 13.70),
    ('serfinanza',    720, 50000000, 14.10),

    -- Banco Pichincha (AA+, campeon del corto plazo, curva plana en largos)
    ('pichincha',      90, 1000000, 11.90),
    ('pichincha',      90, 5000000, 12.20),
    ('pichincha',      90, 50000000, 12.50),
    ('pichincha',     180, 1000000, 12.20),
    ('pichincha',     180, 5000000, 12.50),
    ('pichincha',     180, 50000000, 12.80),
    ('pichincha',     360, 1000000, 12.40),
    ('pichincha',     360, 5000000, 12.70),
    ('pichincha',     360, 50000000, 13.00),
    ('pichincha',     540, 1000000, 12.30),
    ('pichincha',     540, 5000000, 12.60),
    ('pichincha',     540, 50000000, 12.90),
    ('pichincha',     720, 1000000, 12.10),
    ('pichincha',     720, 5000000, 12.40),
    ('pichincha',     720, 50000000, 12.70),

    -- Banco Finandina (AA+, digital, competitivo en medios)
    ('finandina',      90, 200000,  11.10),
    ('finandina',      90, 5000000, 11.40),
    ('finandina',      90, 50000000, 11.70),
    ('finandina',     180, 200000,  11.70),
    ('finandina',     180, 5000000, 12.00),
    ('finandina',     180, 50000000, 12.30),
    ('finandina',     360, 200000,  12.50),
    ('finandina',     360, 5000000, 12.80),
    ('finandina',     360, 50000000, 13.10),
    ('finandina',     540, 200000,  12.60),
    ('finandina',     540, 5000000, 12.90),
    ('finandina',     540, 50000000, 13.20),
    ('finandina',     720, 200000,  12.50),
    ('finandina',     720, 5000000, 12.80),
    ('finandina',     720, 50000000, 13.10),

    -- Pibank (AA+, tasas agresivas)
    ('pibank',         90, 200000,  11.70),
    ('pibank',         90, 5000000, 12.00),
    ('pibank',         90, 50000000, 12.30),
    ('pibank',        180, 200000,  12.10),
    ('pibank',        180, 5000000, 12.40),
    ('pibank',        180, 50000000, 12.70),
    ('pibank',        360, 200000,  12.80),
    ('pibank',        360, 5000000, 13.10),
    ('pibank',        360, 50000000, 13.40),
    ('pibank',        540, 200000,  12.50),
    ('pibank',        540, 5000000, 12.80),
    ('pibank',        540, 50000000, 13.10),
    ('pibank',        720, 200000,  12.30),
    ('pibank',        720, 5000000, 12.60),
    ('pibank',        720, 50000000, 12.90),

    -- Coltefinanciera (AA, especialista en CDTs, gana casi todos los tramos altos)
    ('coltefinanciera', 90, 2000000, 10.90),
    ('coltefinanciera', 90, 10000000, 11.30),
    ('coltefinanciera', 90, 100000000, 11.70),
    ('coltefinanciera',180, 2000000, 11.90),
    ('coltefinanciera',180, 10000000, 12.30),
    ('coltefinanciera',180, 100000000, 12.70),
    ('coltefinanciera',360, 2000000, 12.90),
    ('coltefinanciera',360, 10000000, 13.30),
    ('coltefinanciera',360, 100000000, 13.80),
    ('coltefinanciera',540, 2000000, 13.30),
    ('coltefinanciera',540, 10000000, 13.70),
    ('coltefinanciera',540, 100000000, 14.20),
    ('coltefinanciera',720, 2000000, 13.50),
    ('coltefinanciera',720, 10000000, 13.90),
    ('coltefinanciera',720, 100000000, 14.40),

    -- Nu Colombia (AA, gana en montos pequenos y plazos cortos)
    ('nu',             90, 100000,  12.10),
    ('nu',             90, 5000000, 12.30),
    ('nu',             90, 50000000, 12.50),
    ('nu',            180, 100000,  12.30),
    ('nu',            180, 5000000, 12.50),
    ('nu',            180, 50000000, 12.70),
    ('nu',            360, 100000,  12.60),
    ('nu',            360, 5000000, 12.80),
    ('nu',            360, 50000000, 13.00),
    ('nu',            540, 100000,  12.20),
    ('nu',            540, 5000000, 12.40),
    ('nu',            540, 50000000, 12.60),
    ('nu',            720, 100000,  11.90),
    ('nu',            720, 5000000, 12.10),
    ('nu',            720, 50000000, 12.30)
)
INSERT INTO bank_rates (bank_id, term_days, min_amount, rate)
SELECT b.id, r.term_days, r.min_amount, r.rate
FROM r JOIN banks b ON b.code = r.code;

-- +migrate down

DROP TABLE IF EXISTS bank_rates;
DROP TABLE IF EXISTS banks;
