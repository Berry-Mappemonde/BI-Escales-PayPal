import type { AgStudioLocaleText } from "ag-studio";
import { normalizeAppLang } from "../i18n";

/** French AG Studio / AG Charts chrome (QA: overlays + edit side panels). */
const AG_STUDIO_LOCALE_FR: AgStudioLocaleText = {
  panelTitleFilters: "Filtres",
  panelTitleEdit: "Composer",
  panelTitleData: "Données",
  panelTitleAi: "Assistant IA",
  panelBackAriaLabel: "Retour",
  setupPanelTabWidgets: "Widgets",
  setupPanelTabPage: "Page",
  filterPanelSearchPlaceholder: "Filtrer…",
  filterPanelFilterOperatorAriaLabel: "Opérateur de filtre",
  filterPanelCardDeleteAriaLabel: "Supprimer le filtre",
  filterPanelCardHasEditsAriaLabel: "Modifications non enregistrées",
  filterPanelFromValueAriaLabel: "Valeur minimale du filtre",
  filterPanelToValueAriaLabel: "Valeur maximale du filtre",
  filterPanelValueAriaLabel: "Valeur du filtre",
  filterPanelListAriaLabel: "Liste de filtres",
  filterPanelSearchFilterValuesAriaLabel: "Rechercher des valeurs",
  filterPanelApply: "Appliquer",
  filterPanelCancel: "Annuler",
  layoutPanelFormSectionDimensions: "Dimensions",
  layoutPanelFormMinWidth: "Largeur minimale",
  layoutPanelFormMaxWidth: "Largeur maximale",
  layoutPanelFormHeight: "Hauteur",
  layoutPanelFormGridLines: "Quadrillage",
  layoutPanelFormRowHeight: "Hauteur de ligne",
  layoutPanelFormSectionPage: "Page",
  layoutPanelFormBackground: "Arrière-plan",
  layoutPanelFormSectionWidgets: "Widgets",
  layoutPanelFormWidgetBackgroundColor: "Arrière-plan",
  layoutPanelFormWidgetPadding: "Marges intérieures",
  layoutPanelFormSectionWidgetBorder: "Bordure",
  layoutPanelFormWidgetBorderRadius: "Rayon des coins",
  layoutPanelFormWidgetBorderWidth: "Épaisseur",
  layoutPanelFormWidgetBorderColor: "Couleur",
  layoutPanelFormSectionGrid: "Grille de mise en page",
  layoutPanelFormLayoutColumns: "Colonnes",
  layoutPanelFormLayoutRowHeight: "Hauteur de ligne",
  widgetPanelChangeWidgetType: "Changer le type de widget",
  widgetOverlayNoData: "Aucune donnée à afficher",
  widgetOverlayLoading: "Chargement…",
  dataPanelSectionComputedColumns: "Colonnes calculées",
  dataPanelMenuNewCalculatedColumn: "Nouvelle colonne calculée",
  dataPanelMenuNewMeasure: "Nouvelle mesure",
};

export function agStudioLocaleText(language?: string): AgStudioLocaleText | undefined {
  return normalizeAppLang(language) === "fr" ? AG_STUDIO_LOCALE_FR : undefined;
}

export { AG_STUDIO_LOCALE_FR };
