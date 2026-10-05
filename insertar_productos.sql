-- Script SQL para insertar productos en la base de datos
-- Ejecutar con: python manage.py shell < insertar_productos.sql
-- O importar en SQLite directamente

-- Productos de Cerdo
INSERT INTO core_producto (codigo, nombre, descripcion, categoria_id, precio_compra, precio_venta, stock, stock_minimo, activo) VALUES 
('PRD-0001', 'Cerdo Entero', '', NULL, 0, 0, 12, 0, 1),
('PRD-0002', 'Chicharrón Cerdo', '', NULL, 0, 0, 61, 0, 1),
('PRD-0003', 'Rabo Cerdo', '', NULL, 0, 0, 8, 0, 1),
('PRD-0004', 'Cocote Cerdo', '', NULL, 0, 0, 13, 0, 1),
('PRD-0005', 'Picadillo Cerdo', '', NULL, 0, 0, 20, 0, 1),
('PRD-0006', 'Costillas Cerdo 2 lb', '', NULL, 0, 0, 21, 0, 1),
('PRD-0007', 'Chuletas Cerdo', '', NULL, 0, 0, 29, 0, 1),
('PRD-0008', 'Bistec Cerdo', '', NULL, 0, 0, 15, 0, 1),
('PRD-0009', 'Costilla Cerdo', '', NULL, 0, 0, 20, 0, 1),
('PRD-0010', 'Hueso Cerdo', '', NULL, 0, 0, 38, 0, 1),
('PRD-0011', 'Costilla Cerdo 3 lb', '', NULL, 0, 0, 13, 0, 1),
('PRD-0012', 'Troceado Cerdo', '', NULL, 0, 0, 29, 0, 1);

-- Productos de Res
INSERT INTO core_producto (codigo, nombre, descripcion, categoria_id, precio_compra, precio_venta, stock, stock_minimo, activo) VALUES 
('PRD-0013', 'Costilla Res 4 lb', '', NULL, 0, 0, 121, 0, 1),
('PRD-0014', 'Carne Res Troceado', '', NULL, 0, 0, 27, 0, 1),
('PRD-0015', 'Cocote Res 2 lb', '', NULL, 0, 0, 196, 0, 1),
('PRD-0016', 'Costilla Cerdo 2 lb', '', NULL, 0, 0, 138, 0, 1),
('PRD-0017', 'Picadillo Res 2 lb', '', NULL, 0, 0, 70, 0, 1),
('PRD-0018', 'Picadillo Res', '', NULL, 0, 0, 723, 0, 1),
('PRD-0019', 'Costillas Res 4 lb', '', NULL, 0, 0, 623, 0, 1),
('PRD-0020', 'Bolo Res', '', NULL, 0, 0, 1, 0, 1),
('PRD-0021', 'Cocote Res 3 lb', '', NULL, 0, 0, 167, 0, 1),
('PRD-0022', 'Carne Separada Bolo (1 lb)', '', NULL, 0, 0, 3, 0, 1),
('PRD-0023', 'Carne Separada Bolo (1 kg)', '', NULL, 0, 0, 393, 0, 1),
('PRD-0024', 'Mechillo Cando', '', NULL, 0, 0, 1, 0, 1),
('PRD-0025', 'Bote Res', '', NULL, 0, 0, 2, 0, 1),
('PRD-0026', 'Cave Res Trozados', '', NULL, 0, 0, 6, 0, 1);

-- Productos de Aseo y Otros
INSERT INTO core_producto (codigo, nombre, descripcion, categoria_id, precio_compra, precio_venta, stock, stock_minimo, activo) VALUES 
('PRD-0027', 'Pañales desechables (17a etapa)', '', NULL, 0, 0, 1756, 0, 1),
('PRD-0028', 'Café natural', '', NULL, 0, 0, 2483, 0, 1),
('PRD-0029', 'Toallas húmedas', '', NULL, 0, 0, 38, 0, 1),
('PRD-0030', 'Bombillo 9W', '', NULL, 0, 0, 350, 0, 1),
('PRD-0031', 'Bombillo 15W', '', NULL, 0, 0, 392, 0, 1),
('PRD-0032', 'Chocolate polvo', '', NULL, 0, 0, 2, 0, 1),
('PRD-0033', 'Leche entera', 'Tray: 38, 2 menos', NULL, 0, 0, 36, 0, 1),
('PRD-0034', 'Bombillo 14W', '', NULL, 0, 0, 356, 0, 1),
('PRD-0035', 'Cerveza Solera', '', NULL, 0, 0, 52704, 0, 1),
('PRD-0036', 'Leche semidescremada', 'Tray', NULL, 0, 0, 3660, 0, 1),
('PRD-0037', 'Arroz', '', NULL, 0, 0, 14856, 0, 1);