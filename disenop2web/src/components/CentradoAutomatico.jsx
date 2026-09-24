import { useEffect } from "react";
import { useMap } from "react-leaflet";
import {
  centroParaZonaLibre,
  dentroDeZonaCentral,
  esMovimientoProgramatico,
  moverProgramaticamente,
} from "../utils/mapa";

// Keeps the live position in view WITHOUT fighting the user:
// - it only pans (panTo, animated, zoom unchanged) when the point leaves the
//   central 60 % of the free area, instead of re-centering on every update;
// - a user drag or zoom calls onPausar (the parent pauses it for 15 s);
//   our own flyTo/fitBounds/panTo are ignored thanks to utils/mapa.js.
function CentradoAutomatico({ lat, lon, activo, pausado, onPausar }) {
  const map = useMap();

  useEffect(() => {
    const alArrastrar = () => onPausar();
    const alHacerZoom = () => {
      if (!esMovimientoProgramatico(map)) onPausar();
    };
    map.on("dragstart", alArrastrar);
    map.on("zoomstart", alHacerZoom);
    return () => {
      map.off("dragstart", alArrastrar);
      map.off("zoomstart", alHacerZoom);
    };
  }, [map, onPausar]);

  // Runs on every new position, and again when the pause ends
  useEffect(() => {
    if (!activo || pausado || lat === null || lon === null) return;
    const destino = [lat, lon];
    if (dentroDeZonaCentral(map, destino)) return;
    moverProgramaticamente(map, () =>
      map.panTo(centroParaZonaLibre(map, destino, map.getZoom()), { animate: true })
    );
  }, [map, activo, pausado, lat, lon]);

  return null;
}

export default CentradoAutomatico;
