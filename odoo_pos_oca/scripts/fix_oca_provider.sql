-- Script SQL para forzar la asociación del método Card al proveedor OCA
-- Ejecutar este script directamente en la base de datos

-- 1. Verificar que existen los registros necesarios
SELECT 'Proveedor OCA:' as info, id, name, code FROM payment_provider WHERE code = 'oca';
SELECT 'Método OCA:' as info, id, name, code FROM payment_method WHERE code = 'oca';
SELECT 'Método Card:' as info, id, name, code FROM payment_method WHERE code = 'card';

-- 2. Verificar métodos actuales del proveedor OCA
SELECT 'Métodos actuales del proveedor OCA:' as info;
SELECT pm.name, pm.code, pm.id 
FROM payment_method pm 
JOIN payment_provider_payment_method_rel rel ON pm.id = rel.payment_method_id 
WHERE rel.payment_provider_id = (SELECT id FROM payment_provider WHERE code = 'oca');

-- 3. Limpiar relaciones existentes del proveedor OCA
DELETE FROM payment_provider_payment_method_rel 
WHERE payment_provider_id = (SELECT id FROM payment_provider WHERE code = 'oca');

-- 4. Insertar las nuevas relaciones (OCA + Card)
INSERT INTO payment_provider_payment_method_rel (payment_provider_id, payment_method_id)
SELECT 
    (SELECT id FROM payment_provider WHERE code = 'oca'),
    id
FROM payment_method 
WHERE code IN ('oca', 'card');

-- 5. Verificar que la asociación se hizo correctamente
SELECT 'Métodos después de la asociación:' as info;
SELECT pm.name, pm.code, pm.id 
FROM payment_method pm 
JOIN payment_provider_payment_method_rel rel ON pm.id = rel.payment_method_id 
WHERE rel.payment_provider_id = (SELECT id FROM payment_provider WHERE code = 'oca'); 