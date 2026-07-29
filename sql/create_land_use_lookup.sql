-- Land Use Codes Lookup Table
-- Based on ΦΕΚ 27Α/1980 and later amendments
-- Run this in pgAdmin to create the lookup table

DROP TABLE IF EXISTS epoleodomia.land_use_codes;

CREATE TABLE epoleodomia.land_use_codes (
    code VARCHAR(10) PRIMARY KEY,
    description_el VARCHAR(255) NOT NULL,
    description_en VARCHAR(255),
    category VARCHAR(50),
    parent_code VARCHAR(10)
);

-- Insert common land use codes from ΦΕΚ 27Α/1980
INSERT INTO epoleodomia.land_use_codes (code, description_el, category, parent_code) VALUES
-- Main categories (1-digit or 2-digit codes)
('1', 'Κατοικία', 'ΚΑΤΟΙΚΙΑ', NULL),
('2', 'Κατοικία', 'ΚΑΤΟΙΚΙΑ', NULL),
('21', 'Αμιγής Κατοικία', 'ΚΑΤΟΙΚΙΑ', '2'),
('22', 'Γενική Κατοικία', 'ΚΑΤΟΙΚΙΑ', '2'),
('23', 'Πολεοδομικό Κέντρο', 'ΚΕΝΤΡΟ', '2'),
('24', 'Τουριστική Ζώνη', 'ΤΟΥΡΙΣΜΟΣ', '2'),

-- Specific codes (3-digit)
('211', 'Αμιγής Κατοικία - Μονοκατοικία', 'ΚΑΤΟΙΚΙΑ', '21'),
('212', 'Αμιγής Κατοικία - Πολυκατοικία', 'ΚΑΤΟΙΚΙΑ', '21'),
('221', 'Γενική Κατοικία - Μονοκατοικία', 'ΚΑΤΟΙΚΙΑ', '22'),
('222', 'Γενική Κατοικία - Πολυκατοικία', 'ΚΑΤΟΙΚΙΑ', '22'),

-- Other categories
('3', 'Εμπόριο', 'ΕΜΠΟΡΙΟ', NULL),
('4', 'Βιομηχανία - Βιοτεχνία', 'ΒΙΟΜΗΧΑΝΙΑ', NULL),
('5', 'Αναψυχή - Πολιτισμός', 'ΑΝΑΨΥΧΗ', NULL),
('6', 'Κοινωφελείς Εξυπηρετήσεις', 'ΚΟΙΝΩΦΕΛΗ', NULL),
('7', 'Ελεύθεροι Χώροι - Πράσινο', 'ΠΡΑΣΙΝΟ', NULL);

-- Create index
CREATE INDEX idx_land_use_codes_category ON epoleodomia.land_use_codes(category);

-- Function to translate code list to description
CREATE OR REPLACE FUNCTION epoleodomia.translate_land_use_codes(codes_str VARCHAR)
RETURNS VARCHAR AS $$
DECLARE
    result VARCHAR := '';
    current_code VARCHAR;
    desc_el VARCHAR;
    codes_array VARCHAR[];
BEGIN
    IF codes_str IS NULL OR codes_str = '' THEN
        RETURN NULL;
    END IF;

    -- Split by semicolon
    codes_array := string_to_array(codes_str, ';');

    -- Get the main category from first 2-digit code
    FOREACH current_code IN ARRAY codes_array LOOP
        current_code := trim(current_code);
        IF length(current_code) = 2 THEN
            SELECT luc.description_el INTO desc_el
            FROM epoleodomia.land_use_codes luc
            WHERE luc.code = current_code;

            IF desc_el IS NOT NULL THEN
                RETURN desc_el;
            END IF;
        END IF;
    END LOOP;

    -- If no 2-digit code found, try first code
    current_code := trim(codes_array[1]);
    SELECT luc.description_el INTO desc_el
    FROM epoleodomia.land_use_codes luc
    WHERE luc.code = current_code;

    RETURN COALESCE(desc_el, codes_str);
END;
$$ LANGUAGE plpgsql;

-- Test the function
SELECT epoleodomia.translate_land_use_codes('21;22;211') as translated;
-- Should return: "Αμιγής Κατοικία"

SELECT epoleodomia.translate_land_use_codes('211;21;22') as translated;
-- Should return: "Αμιγής Κατοικία" (from code 21)
