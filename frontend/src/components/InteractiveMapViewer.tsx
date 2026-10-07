import React, { useEffect, useRef, useState } from 'react';
import { MapPin, Navigation, Compass, Globe } from 'lucide-react';
import type { GeoLocationItem } from '../api';

interface InteractiveMapViewerProps {
  locations: GeoLocationItem[];
}

export const InteractiveMapViewer: React.FC<InteractiveMapViewerProps> = ({ locations }) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const [selectedLocation, setSelectedLocation] = useState<GeoLocationItem | null>(locations[0] || null);

  useEffect(() => {
    if (!mapContainerRef.current || locations.length === 0) return;

    let isMounted = true;

    // Dynamically initialize Leaflet
    import('leaflet').then((L) => {
      if (!isMounted || !mapContainerRef.current) return;

      // Clean up previous instance if exists
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
      if ((mapContainerRef.current as any)._leaflet_id) {
        delete (mapContainerRef.current as any)._leaflet_id;
      }

      const primary = locations[0];
      const initialCenter: [number, number] = [primary.lat, primary.lon];

      const map = L.map(mapContainerRef.current, {
        center: initialCenter,
        zoom: locations.length > 1 ? 4 : 8,
        zoomControl: false,
        attributionControl: false
      });

      mapInstanceRef.current = map;

      // Use CartoDB Dark Matter tiles for ultra-sleek dark aesthetic
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd',
      }).addTo(map);

      // Add zoom control in top-right
      L.control.zoom({ position: 'topright' }).addTo(map);

      // Create glowing neon markers and highlight circles for each location
      const markersGroup = L.featureGroup();

      locations.forEach((loc) => {
        const color = loc.highlight_color || '#3b82f6';

        // 1. Highlight area circle with glowing pulse
        const radius = loc.radius_meters || 30000;
        const circle = L.circle([loc.lat, loc.lon], {
          radius: radius,
          color: color,
          weight: 1.5,
          opacity: 0.8,
          fillColor: color,
          fillOpacity: 0.15
        }).addTo(map);

        // 2. Custom Neon Glowing Pin using L.divIcon
        const customIcon = L.divIcon({
          className: 'custom-geo-marker',
          html: `
            <div style="
              position: relative;
              width: 32px;
              height: 32px;
              display: flex;
              align-items: center;
              justify-content: center;
            ">
              <div style="
                position: absolute;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background-color: ${color};
                opacity: 0.35;
                animation: ping 2s cubic-bezier(0, 0, 0.2, 1) infinite;
              "></div>
              <div style="
                position: relative;
                width: 16px;
                height: 16px;
                border-radius: 50%;
                background-color: ${color};
                border: 2px solid #ffffff;
                box-shadow: 0 0 12px ${color};
                cursor: pointer;
              "></div>
            </div>
          `,
          iconSize: [32, 32],
          iconAnchor: [16, 16]
        });

        const marker = L.marker([loc.lat, loc.lon], { icon: customIcon }).addTo(map);

        marker.on('click', () => {
          setSelectedLocation(loc);
          map.flyTo([loc.lat, loc.lon], 10, { duration: 1.2 });
        });

        markersGroup.addLayer(circle);
        markersGroup.addLayer(marker);
      });

      if (locations.length > 1) {
        map.fitBounds(markersGroup.getBounds().pad(0.2));
      }
    }).catch((err) => {
      console.warn("Leaflet map load notice:", err);
    });

    return () => {
      isMounted = false;
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
      if (mapContainerRef.current && (mapContainerRef.current as any)._leaflet_id) {
        delete (mapContainerRef.current as any)._leaflet_id;
      }
    };
  }, [locations]);

  const handleFlyTo = (loc: GeoLocationItem) => {
    setSelectedLocation(loc);
    if (mapInstanceRef.current) {
      mapInstanceRef.current.flyTo([loc.lat, loc.lon], 11, { duration: 1.2 });
    }
  };

  const handleFitAll = () => {
    if (mapInstanceRef.current && locations.length > 0) {
      import('leaflet').then((L) => {
        const bounds = L.latLngBounds(locations.map(l => [l.lat, l.lon]));
        mapInstanceRef.current.fitBounds(bounds.pad(0.3));
      });
    }
  };

  return (
    <div style={{
      margin: '1rem 0',
      backgroundColor: '#0b0f19',
      border: '1px solid rgba(59, 130, 246, 0.25)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.45)'
    }}>
      {/* Header bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.65rem 1rem',
        backgroundColor: 'rgba(15, 23, 42, 0.75)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Globe size={15} style={{ color: 'var(--accent-primary)' }} />
          <span style={{ fontSize: '0.85rem', fontWeight: 650, color: 'var(--text-primary)' }}>
            Interactive Geographical Intelligence
          </span>
          <span style={{
            fontSize: '0.68rem',
            padding: '0.12rem 0.45rem',
            borderRadius: '9999px',
            backgroundColor: 'rgba(59, 130, 246, 0.15)',
            color: '#93c5fd',
            fontFamily: 'var(--font-mono)'
          }}>
            {locations.length} {locations.length === 1 ? 'Location' : 'Locations'} Highlighted
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <button
            onClick={handleFitAll}
            title="Reset Map to View All Locations"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.3rem',
              fontSize: '0.72rem',
              color: 'var(--text-dim)',
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              padding: '0.2rem 0.5rem',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer'
            }}
          >
            <Compass size={12} />
            <span>Fit All</span>
          </button>
        </div>
      </div>

      {/* Main Map + Side Card Container */}
      <div style={{ position: 'relative', width: '100%', height: '340px' }}>
        {/* Leaflet map container */}
        <div
          ref={mapContainerRef}
          style={{ width: '100%', height: '100%', backgroundColor: '#090d16' }}
        />

        {/* Floating Interactive Location Card */}
        {selectedLocation && (
          <div style={{
            position: 'absolute',
            bottom: '12px',
            left: '12px',
            zIndex: 1000,
            maxWidth: '360px',
            backgroundColor: 'rgba(15, 23, 42, 0.88)',
            backdropFilter: 'blur(12px)',
            border: `1px solid ${selectedLocation.highlight_color || 'var(--accent-primary)'}55`,
            borderRadius: 'var(--radius-md)',
            padding: '0.85rem',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.65)',
            animation: 'fadeIn 0.25s ease-out'
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginBottom: '0.2rem' }}>
                  <MapPin size={14} style={{ color: selectedLocation.highlight_color || '#3b82f6' }} />
                  <span style={{ fontSize: '0.88rem', fontWeight: 650, color: '#ffffff' }}>
                    {selectedLocation.name}
                  </span>
                </div>
                <span style={{ fontSize: '0.72rem', color: '#93c5fd', fontFamily: 'var(--font-mono)' }}>
                  {selectedLocation.region} • {selectedLocation.country}
                </span>
              </div>

              <button
                onClick={() => handleFlyTo(selectedLocation)}
                title="Center Camera on this Location"
                style={{
                  padding: '0.25rem 0.45rem',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'rgba(59, 130, 246, 0.15)',
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  color: '#93c5fd',
                  fontSize: '0.7rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.25rem',
                  cursor: 'pointer'
                }}
              >
                <Navigation size={11} />
                <span>Fly To</span>
              </button>
            </div>

            <p style={{
              fontSize: '0.78rem',
              color: 'var(--text-secondary)',
              lineHeight: 1.5,
              margin: '0.5rem 0 0.65rem 0'
            }}>
              {selectedLocation.description}
            </p>

            {/* Operating Entities Tags */}
            {selectedLocation.entities && selectedLocation.entities.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.4rem' }}>
                {selectedLocation.entities.map((ent, idx) => (
                  <span key={idx} style={{
                    fontSize: '0.68rem',
                    padding: '0.1rem 0.4rem',
                    borderRadius: '4px',
                    backgroundColor: 'rgba(255, 255, 255, 0.08)',
                    color: 'var(--text-primary)',
                    fontFamily: 'var(--font-mono)'
                  }}>
                    {ent}
                  </span>
                ))}
              </div>
            )}

            {/* Coordinates & Radius Bar */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginTop: '0.65rem',
              paddingTop: '0.45rem',
              borderTop: '1px solid rgba(255, 255, 255, 0.08)',
              fontSize: '0.68rem',
              color: 'var(--text-dim)',
              fontFamily: 'var(--font-mono)'
            }}>
              <span>Coordinates: {selectedLocation.lat.toFixed(4)}°N, {selectedLocation.lon.toFixed(4)}°E</span>
              <span>Radius: {((selectedLocation.radius_meters || 30000) / 1000).toFixed(0)} km</span>
            </div>
          </div>
        )}
      </div>

      {/* Location Picker Tabs if multiple locations */}
      {locations.length > 1 && (
        <div style={{
          display: 'flex',
          gap: '0.5rem',
          padding: '0.5rem 0.85rem',
          backgroundColor: 'rgba(15, 23, 42, 0.5)',
          borderTop: '1px solid rgba(255, 255, 255, 0.04)',
          overflowX: 'auto'
        }}>
          {locations.map((loc) => (
            <button
              key={loc.id}
              onClick={() => handleFlyTo(loc)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                fontSize: '0.74rem',
                padding: '0.25rem 0.6rem',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: selectedLocation?.id === loc.id ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255, 255, 255, 0.04)',
                border: selectedLocation?.id === loc.id ? '1px solid var(--accent-primary)' : '1px solid rgba(255, 255, 255, 0.06)',
                color: selectedLocation?.id === loc.id ? '#ffffff' : 'var(--text-secondary)',
                cursor: 'pointer',
                whiteSpace: 'nowrap'
              }}
            >
              <div style={{
                width: '7px',
                height: '7px',
                borderRadius: '50%',
                backgroundColor: loc.highlight_color || '#3b82f6'
              }} />
              <span>{loc.name.split(',')[0]}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
