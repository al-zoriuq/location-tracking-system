import "./App.css";
import "leaflet/dist/leaflet.css";
import { useState } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";

function App() {
  const [location, setLocation] = useState([51.505, -0.09]);

  return (
    <div className="centrado">
      <p>arriba del mapa</p>
      <MapContainer
        center={[51.505, -0.09]}
        zoom={13}
        scrollWheelZoom={true}
        className="map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Marker position={location}>
          <Popup>
            A pretty CSS3 popup. <br /> Easily customizable.
          </Popup>
        </Marker>
      </MapContainer>
      {<button onClick={() => setLocation([40.7128, -74.006])}>ola</button>}
      <p>texto</p>
    </div>
  );
}

export default App;
