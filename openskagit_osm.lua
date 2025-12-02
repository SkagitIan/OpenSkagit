-- openskagit_osm.lua
-- Flex style for osm2pgsql that creates thematic tables needed for distance metrics.

local srid = 4326  -- native OSM SRID; we'll reproject to 2926 later in PostGIS

-- Helper: define a point table
local function point_table(name)
    return osm2pgsql.define_table({
        name = name,
        schema = 'osm',
        ids = { type = 'node', id_column = 'osm_id' },
        columns = {
            { column = 'geom',  type = 'point', not_null = true, projection = srid },
            { column = 'name',  type = 'text' },
            { column = 'tags',  type = 'hstore' }
        }
    })
end

-- Helper: define a linestring table
local function line_table(name)
    return osm2pgsql.define_table({
        name = name,
        schema = 'osm',
        ids = { type = 'way', id_column = 'osm_id' },
        columns = {
            { column = 'geom',  type = 'linestring', not_null = true, projection = srid },
            { column = 'name',  type = 'text' },
            { column = 'tags',  type = 'hstore' }
        }
    })
end

-- Helper: define polygon table
local function polygon_table(name)
    return osm2pgsql.define_table({
        name = name,
        schema = 'osm',
        ids = { type = 'way', id_column = 'osm_id' },
        columns = {
            { column = 'geom',  type = 'polygon', not_null = true, projection = srid },
            { column = 'name',  type = 'text' },
            { column = 'tags',  type = 'hstore' }
        }
    })
end

-- Thematic tables
local schools      = point_table('osm_schools')         -- amenity=school, college, university
local parks        = polygon_table('osm_parks')         -- leisure=park, recreation_ground, landuse=recreation_ground
local supermarkets = point_table('osm_supermarkets')    -- shop=supermarket/grocery/convenience
local hospitals    = point_table('osm_hospitals')       -- amenity=hospital/clinic
local firestations = point_table('osm_fire_stations')   -- amenity=fire_station
local trailheads   = point_table('osm_trailheads')      -- tourism=trailhead
local citycenters  = point_table('osm_city_centers')    -- place=city/town/village/hamlet/suburb

local major_roads  = line_table('osm_major_roads')      -- motorway, trunk, primary, secondary
local minor_roads  = line_table('osm_minor_roads')      -- tertiary, residential, unclassified, service, living_street

-- Helper: read tag with nil-safe
local function tag(v, key)
    return v.tags[key]
end

-- NODES ----------------------------------------------------------------------

function osm2pgsql.process_node(object)
    if not object.tags then return end

    local amenity = tag(object, 'amenity')
    local shop    = tag(object, 'shop')
    local tourism = tag(object, 'tourism')
    local place   = tag(object, 'place')

    -- Schools
    if amenity == 'school' or amenity == 'college' or amenity == 'university' then
        schools:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end

    -- Supermarkets / groceries / convenience
    if shop == 'supermarket' or shop == 'grocery' or shop == 'convenience' then
        supermarkets:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end

    -- Hospitals / clinics
    if amenity == 'hospital' or amenity == 'clinic' then
        hospitals:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end

    -- Fire stations
    if amenity == 'fire_station' then
        firestations:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end

    -- Trailheads
    if tourism == 'trailhead' then
        trailheads:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end

    -- City centers (settlement points)
    if place == 'city' or place == 'town' or place == 'village'
        or place == 'hamlet' or place == 'suburb' then
        citycenters:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end
end

-- WAYS / POLYGONS -----------------------------------------------------------

function osm2pgsql.process_way(object)
    if not object.tags then return end

    local highway = tag(object, 'highway')
    local leisure = tag(object, 'leisure')
    local landuse = tag(object, 'landuse')

    -- Major roads
    if highway == 'motorway' or highway == 'trunk'
        or highway == 'primary' or highway == 'secondary' then
        major_roads:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end

    -- Minor roads
    if highway == 'tertiary' or highway == 'residential'
        or highway == 'unclassified' or highway == 'service'
        or highway == 'living_street' then
        minor_roads:add_row{
            geom = object,
            name = tag(object, 'name'),
            tags = object.tags
        }
    end

    -- Parks (polygons)
    if leisure == 'park' or leisure == 'recreation_ground'
        or landuse == 'recreation_ground' then
        if object.is_closed then
            parks:add_row{
                geom = object,
                name = tag(object, 'name'),
                tags = object.tags
            }
        end
    end
end

-- Relations are ignored for now (keeps style simple). You can extend later.
function osm2pgsql.process_relation(object)
    -- no-op for now
end
