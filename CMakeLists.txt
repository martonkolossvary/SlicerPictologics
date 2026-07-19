cmake_minimum_required(VERSION 3.28.0...3.28.0 FATAL_ERROR)

project(SlicerPictologics)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/martonkolossvary/SlicerPictologics")
set(EXTENSION_CONTRIBUTORS "Márton Kolossváry")
set(EXTENSION_DESCRIPTION "Run Pictologics radiomic feature extraction from 3D Slicer")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/martonkolossvary/SlicerPictologics/main/PictologicsSlicer/Resources/Icons/PictologicsSlicer.svg")
set(EXTENSION_SCREENSHOTURLS "")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(PictologicsSlicer)
add_subdirectory(PictologicsCLI)

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
