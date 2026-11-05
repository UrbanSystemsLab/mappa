// Interface text in both languages, as on the current site.
import type { Lang } from './catalog';

export const I18N = {
  es: { tagline: 'Asistente de planificación y riesgos de Puerto Rico',
        ph: 'Escribe tu pregunta… o haz clic en el mapa', clear: 'Nueva conversación',
        sources: 'Fuentes', next: 'Podrías preguntar', emptyT: '¡Aló!',
        emptyB: 'Pregúntale a Mappa sobre uso de terrenos, riesgo de inundación o deslizamiento, permisos y planificación en Puerto Rico. También puedes hacer clic en el mapa para preguntar sobre un lugar. Puedes preguntar en español o en inglés.',
        hint: ['Cada respuesta cita su fuente.', ' Si los documentos cargados no lo dicen, Mappa lo dirá en vez de inventarlo.'],
        ask: 'Preguntar', removeFilter: 'Quitar filtro', thinking: 'Consultando',
        samples: [['Zona inundable', '¿Puedo construir en una zona inundable?'],
                  ['Permisos', '¿Qué regula el Reglamento Conjunto?'],
                  ['Escuelas', '¿Cuántas escuelas hay en Adjuntas?'],
                  ['Deslizamientos', '¿Dónde hay riesgo de deslizamiento?']] },
  en: { tagline: 'Planning & hazard assistant for Puerto Rico',
        ph: 'Type your question… or click the map', clear: 'New conversation',
        sources: 'Sources', next: 'You could ask', emptyT: '¡Aló!',
        emptyB: 'Ask Mappa about land use, flood or landslide risk, permits, and planning in Puerto Rico. You can also click the map to ask about a place. Ask questions in Spanish or English.',
        hint: ['Every answer cites its source.', ' If the loaded documents do not say it, Mappa will say so rather than fill the gap.'],
        ask: 'Ask', removeFilter: 'Remove filter', thinking: 'Thinking',
        samples: [['Flood zone', 'Can I build in a flood zone?'],
                  ['Permits', 'What does the Reglamento Conjunto regulate?'],
                  ['Schools', 'How many schools are in Adjuntas?'],
                  ['Landslides', 'Where is there landslide risk?']] },
} satisfies Record<Lang, unknown>;
