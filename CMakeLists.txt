cmake_minimum_required(VERSION 3.28.0...3.28.0 FATAL_ERROR)

project(Pictologics)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/martonkolossvary/SlicerPictologics")
set(EXTENSION_CONTRIBUTORS "Márton Kolossváry")
set(EXTENSION_CATEGORY "Informatics")
set(EXTENSION_DESCRIPTION "Extract quantitative measurements of image intensity, shape, and texture from 3D images and segmented regions using Pictologics. Review and export results with preprocessing and software provenance. For research use only; not for clinical diagnosis or treatment decisions.")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/martonkolossvary/SlicerPictologics/main/assets/branding/pictologics/slicer/Pictologics-128.png")
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
