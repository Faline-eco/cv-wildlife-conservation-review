from __future__ import annotations
from pydantic import BaseModel, Field

"""
Auto-generated from the IUCN habitats dictionary.

Rules:
- Level-1 codes (e.g., "1.") become classes.
- Level-2 codes without children become boolean fields on their Level-1 class.
- Level-2 codes WITH children become their own classes (fields are the Level-3 leaves),
  and the corresponding field on the Level-1 class is typed as that class.
"""


class MarineNeriticMarineNeriticCoralReef(BaseModel):
    outer_reef_channel: bool = Field(False, description='Outer reef channel')
    back_slope: bool = Field(False, description='Back slope')
    foreslope_outer_reef_slope: bool = Field(False, description='Foreslope (outer reef slope)')
    lagoon: bool = Field(False, description='Lagoon')
    inter_reef_soft_substrate: bool = Field(False, description='Inter-reef soft substrate')
    inter_reef_rubble_substrate: bool = Field(False, description='Inter-reef rubble substrate')


class MarineDeepOceanFloorBenthicAndDemersalContinentalSlopeBathylZone2004000M(BaseModel):
    hard_substrate: bool = Field(False, description='Hard Substrate')
    soft_substrate: bool = Field(False, description='Soft Substrate')


class Forest(BaseModel):
    boreal: bool = Field(False, description='Forest - Boreal')
    subarctic: bool = Field(False, description='Forest - Subarctic')
    subantarctic: bool = Field(False, description='Forest - Subantarctic')
    temperate: bool = Field(False, description='Forest - Temperate')
    subtropical_tropical_dry: bool = Field(False, description='Forest - Subtropical/tropical dry')
    subtropical_tropical_moist_lowland: bool = Field(False, description='Forest - Subtropical/tropical moist lowland')
    subtropical_tropical_mangrove_vegetation_above_high_tide_level: bool = Field(False,
                                                                                 description='Forest - Subtropical/tropical mangrove vegetation above high tide level')
    subtropical_tropical_swamp: bool = Field(False, description='Forest - Subtropical/tropical swamp')
    subtropical_tropical_moist_montane: bool = Field(False, description='Forest - Subtropical/tropical moist montane')


class Savanna(BaseModel):
    dry: bool = Field(False, description='Savanna - Dry')
    moist: bool = Field(False, description='Savanna - Moist')


class Shrubland(BaseModel):
    subarctic: bool = Field(False, description='Shrubland - Subarctic')
    subantarctic: bool = Field(False, description='Shrubland - Subantarctic')
    boreal: bool = Field(False, description='Shrubland - Boreal')
    temperate: bool = Field(False, description='Shrubland - Temperate')
    subtropical_tropical_dry: bool = Field(False, description='Shrubland - Subtropical/tropical dry')
    subtropical_tropical_moist: bool = Field(False, description='Shrubland - Subtropical/tropical moist')
    subtropical_tropical_high_altitude: bool = Field(False,
                                                     description='Shrubland - Subtropical/tropical high altitude')
    mediterranean_type_shrubby_vegetation: bool = Field(False,
                                                        description='Shrubland - Mediterranean-type shrubby vegetation')


class Grassland(BaseModel):
    tundra: bool = Field(False, description='Grassland - Tundra')
    subarctic: bool = Field(False, description='Grassland - Subarctic')
    subantarctic: bool = Field(False, description='Grassland - Subantarctic')
    temperate: bool = Field(False, description='Grassland - Temperate')
    subtropical_tropical_dry: bool = Field(False, description='Grassland - Subtropical/tropical dry')
    subtropical_tropical_seasonally_wet_flooded: bool = Field(False,
                                                              description='Grassland - Subtropical/tropical seasonally wet/flooded')
    subtropical_tropical_high_altitude: bool = Field(False,
                                                     description='Grassland - Subtropical/tropical high altitude')


class WetlandsInland(BaseModel):
    permanent_rivers_streams_creeks_includes_waterfalls: bool = Field(False,
                                                                      description='Wetlands (inland) - Permanent rivers/streams/creeks (includes waterfalls)')
    seasonal_intermittent_irregular_rivers_streams_creeks: bool = Field(False,
                                                                        description='Wetlands (inland) - Seasonal/intermittent/irregular rivers/streams/creeks')
    shrub_dominated_wetlands: bool = Field(False, description='Wetlands (inland) - Shrub dominated wetlands')
    bogs_marshes_swamps_fens_peatlands: bool = Field(False,
                                                     description='Wetlands (inland) - Bogs, marshes, swamps, fens, peatlands')
    permanent_freshwater_lakes_over_8_ha: bool = Field(False,
                                                       description='Wetlands (inland) - Permanent freshwater lakes (over 8 ha)')
    seasonal_intermittent_freshwater_lakes_over_8_ha: bool = Field(False,
                                                                   description='Wetlands (inland) - Seasonal/intermittent freshwater lakes (over 8 ha)')
    permanent_freshwater_marshes_pools_under_8_ha: bool = Field(False,
                                                                description='Wetlands (inland) - Permanent freshwater marshes/pools (under 8 ha)')
    seasonal_intermittent_freshwater_marshes_pools_under_8_ha: bool = Field(False,
                                                                            description='Wetlands (inland) - Seasonal/intermittent freshwater marshes/pools (under 8 ha)')
    freshwater_springs_and_oases: bool = Field(False, description='Wetlands (inland) - Freshwater springs and oases')
    tundra_wetlands_inc_pools_and_temporary_waters_from_snowmelt: bool = Field(False,
                                                                               description='Wetlands (inland) - Tundra wetlands (inc. pools and temporary waters from snowmelt)')
    alpine_wetlands_inc_temporary_waters_from_snowmelt: bool = Field(False,
                                                                     description='Wetlands (inland) - Alpine wetlands (inc. temporary waters from snowmelt)')
    geothermal_wetlands: bool = Field(False, description='Wetlands (inland) - Geothermal wetlands')
    permanent_inland_deltas: bool = Field(False, description='Wetlands (inland) - Permanent inland deltas')
    permanent_saline_brackish_or_alkaline_lakes: bool = Field(False,
                                                              description='Wetlands (inland) - Permanent saline, brackish or alkaline lakes')
    seasonal_intermittent_saline_brackish_or_alkaline_lakes_and_flats: bool = Field(False,
                                                                                    description='Wetlands (inland) - Seasonal/intermittent saline, brackish or alkaline lakes and flats')
    permanent_saline_brackish_or_alkaline_marshes_pools: bool = Field(False,
                                                                      description='Wetlands (inland) - Permanent saline, brackish or alkaline marshes/pools')
    seasonal_intermittent_saline_brackish_or_alkaline_marshes_pools: bool = Field(False,
                                                                                  description='Wetlands (inland) - Seasonal/intermittent saline, brackish or alkaline marshes/pools')
    karst_and_other_subterranean_hydrological_systems_inland: bool = Field(False,
                                                                           description='Wetlands (inland) - Karst and other subterranean hydrological systems (inland)')


class RockyAreasEGInlandCliffsMountainPeaks(BaseModel):
    rocky_areas: bool = Field(False, description="Rocky Areas (e.g., inland cliffs, mountain peaks)")


class CavesSubterraneanHabitatsNonAquatic(BaseModel):
    caves_and_subterranean_habitats_non_aquatic_caves: bool = Field(False,
                                                                    description='Caves and Subterranean Habitats (non-aquatic) - Caves')
    caves_and_subterranean_habitats_non_aquatic_other_subterranean_habitats: bool = Field(False,
                                                                                          description='Caves and Subterranean Habitats (non-aquatic) - Other subterranean habitats')


class Desert(BaseModel):
    hot: bool = Field(False, description='Desert - Hot')
    temperate: bool = Field(False, description='Desert - Temperate')
    cold: bool = Field(False, description='Desert - Cold')


class MarineNeritic(BaseModel):
    pelagic: bool = Field(False, description='Marine Neritic - Pelagic')
    subtidal_rock_and_rocky_reefs: bool = Field(False, description='Marine Neritic - Subtidal rock and rocky reefs')
    subtidal_loose_rock_pebble_gravel: bool = Field(False,
                                                    description='Marine Neritic - Subtidal loose rock/pebble/gravel')
    subtidal_sandy: bool = Field(False, description='Marine Neritic - Subtidal sandy')
    subtidal_sandy_mud: bool = Field(False, description='Marine Neritic - Subtidal sandy-mud')
    subtidal_muddy: bool = Field(False, description='Marine Neritic - Subtidal muddy')
    macroalgal_kelp: bool = Field(False, description='Marine Neritic - Macroalgal/kelp')
    coral_reef: MarineNeriticMarineNeriticCoralReef = Field(default_factory=MarineNeriticMarineNeriticCoralReef,
                                                            description='Marine Neritic - Coral Reef')
    seagrass_submerged: bool = Field(False, description=' Seagrass (Submerged)')
    estuaries: bool = Field(False, description='Estuaries')


class MarineOceanic(BaseModel):
    epipelagic_0_200_m: bool = Field(False, description='Epipelagic (0-200 m)')
    mesopelagic_200_1_000_m: bool = Field(False, description='Mesopelagic (200-1,000 m)')
    bathypelagic_1_000_4_000_m: bool = Field(False, description='Bathypelagic (1,000-4,000 m)')
    abyssopelagic_4_000_6_000_m: bool = Field(False, description='Abyssopelagic (4,000-6,000 m)')


class MarineDeepOceanFloorBenthicAndDemersal(BaseModel):
    continental_slope_bathyl_zone_200_4_000_m: MarineDeepOceanFloorBenthicAndDemersalContinentalSlopeBathylZone2004000M = Field(
        default_factory=MarineDeepOceanFloorBenthicAndDemersalContinentalSlopeBathylZone2004000M,
        description='Continental Slope/Bathyl Zone (200-4,000 m)')
    abyssal_plain_4_000_6_000_m: bool = Field(False, description='Abyssal Plain (4,000-6,000 m)')
    abyssal_mountain_hills_4_000_6_000_m: bool = Field(False, description='Abyssal Mountain/Hills (4,000-6,000 m)')
    hadal_deep_sea_trench_6_000_m: bool = Field(False, description='Hadal/Deep Sea Trench (>6,000 m)')
    seamount: bool = Field(False, description='Seamount')
    deep_sea_vents_rifts_seeps: bool = Field(False, description='Deep Sea Vents (Rifts/Seeps)')


class MarineIntertidal(BaseModel):
    rocky_shoreline: bool = Field(False, description='Rocky Shoreline')
    sandy_shoreline_and_or_beaches_sand_bars_spits_etc: bool = Field(False,
                                                                     description='Sandy Shoreline and/or Beaches, Sand Bars, Spits, etc.')
    shingle_and_or_pebble_shoreline_and_or_beaches: bool = Field(False,
                                                                 description='Shingle and/or Pebble Shoreline and/or Beaches')
    mud_shoreline_and_intertidal_mud_flats: bool = Field(False, description='Mud Shoreline and Intertidal Mud Flats')
    salt_marshes_emergent_grasses: bool = Field(False, description='Salt Marshes (Emergent Grasses)')
    tidepools: bool = Field(False, description='Tidepools')
    mangrove_submerged_roots: bool = Field(False, description='Mangrove Submerged Roots')


class MarineCoastalSupratidal(BaseModel):
    sea_cliffs_and_rocky_offshore_islands: bool = Field(False, description='Sea Cliffs and Rocky Offshore Islands')
    coastal_caves_karst: bool = Field(False, description='Coastal Caves/Karst')
    coastal_sand_dunes: bool = Field(False, description='Coastal Sand Dunes')
    coastal_brackish_saline_lagoons_marine_lakes: bool = Field(False,
                                                               description='Coastal Brackish/Saline Lagoons/Marine Lakes')
    coastal_freshwater_lakes: bool = Field(False, description='Coastal Freshwater Lakes')


class ArtificialTerrestrial(BaseModel):
    arable_land: bool = Field(False, description='Arable Land')
    pastureland: bool = Field(False, description='Pastureland')
    plantations: bool = Field(False, description='Plantations')
    rural_gardens: bool = Field(False, description='Rural Gardens')
    urban_areas: bool = Field(False, description='Urban Areas')
    subtropical_tropical_heavily_degraded_former_forest: bool = Field(False,
                                                                      description='Subtropical/Tropical Heavily Degraded Former Forest')


class ArtificialAquatic(BaseModel):
    water_storage_areas_over_8_ha: bool = Field(False, description='Water Storage Areas [over 8 ha]')
    ponds_below_8_ha: bool = Field(False, description='Ponds [below 8 ha]')
    aquaculture_ponds: bool = Field(False, description='Aquaculture Ponds')
    salt_exploitation_sites: bool = Field(False, description='Salt Exploitation Sites')
    excavations_open: bool = Field(False, description='Excavations (open)')
    wastewater_treatment_areas: bool = Field(False, description='Wastewater Treatment Areas')
    irrigated_land_includes_irrigation_channels: bool = Field(False,
                                                              description='Irrigated Land [includes irrigation channels]')
    seasonally_flooded_agricultural_land: bool = Field(False, description='Seasonally Flooded Agricultural Land')
    canals_and_drainage_channels_ditches: bool = Field(False, description='Canals and Drainage Channels, Ditches')
    karst_and_other_subterranean_hydrological_systems_human_made: bool = Field(False,
                                                                               description='Karst and Other Subterranean Hydrological Systems [human-made]')
    marine_anthropogenic_structures: bool = Field(False, description='Marine Anthropogenic Structures')
    mariculture_cages: bool = Field(False, description='Mariculture Cages')
    mari_brackish_culture_ponds: bool = Field(False, description='Mari/Brackish-culture Ponds')


class Unknown(BaseModel):
    unknown: bool = Field(False, description='Unknown habitat')


class IUCNHabitats(BaseModel):
    forest: Forest = Field(default_factory=Forest, description='Forest')
    savanna: Savanna = Field(default_factory=Savanna, description='Savanna')
    shrubland: Shrubland = Field(default_factory=Shrubland, description='Shrubland')
    grassland: Grassland = Field(default_factory=Grassland, description='Grassland')
    wetlands_inland: WetlandsInland = Field(default_factory=WetlandsInland, description='Wetlands (inland)')
    rocky_areas_e_g_inland_cliffs_mountain_peaks: RockyAreasEGInlandCliffsMountainPeaks = Field(
        default_factory=RockyAreasEGInlandCliffsMountainPeaks,
        description='Rocky Areas (e.g., inland cliffs, mountain peaks)')
    caves_subterranean_habitats_non_aquatic: CavesSubterraneanHabitatsNonAquatic = Field(
        default_factory=CavesSubterraneanHabitatsNonAquatic, description='Caves & Subterranean Habitats (non-aquatic)')
    desert: Desert = Field(default_factory=Desert, description='Desert')
    marine_neritic: MarineNeritic = Field(default_factory=MarineNeritic, description='Marine Neritic')
    marine_oceanic: MarineOceanic = Field(default_factory=MarineOceanic, description='Marine Oceanic')
    marine_deep_ocean_floor_benthic_and_demersal: MarineDeepOceanFloorBenthicAndDemersal = Field(
        default_factory=MarineDeepOceanFloorBenthicAndDemersal,
        description='Marine Deep Ocean Floor (Benthic and Demersal)')
    marine_intertidal: MarineIntertidal = Field(default_factory=MarineIntertidal, description='Marine Intertidal')
    marine_coastal_supratidal: MarineCoastalSupratidal = Field(default_factory=MarineCoastalSupratidal,
                                                               description='Marine Coastal/Supratidal')
    artificial_terrestrial: ArtificialTerrestrial = Field(default_factory=ArtificialTerrestrial,
                                                          description='Artificial - Terrestrial')
    artificial_aquatic: ArtificialAquatic = Field(default_factory=ArtificialAquatic, description='Artificial - Aquatic')
    unknown: Unknown = Field(default_factory=Unknown, description='Unknown')