/**
 * Google Drive Picker integration.
 *
 * Opens a full Drive file browser (folder-navigable) filtered to image files.
 * When the user confirms their selection, dispatches a 'driveFilesSelected'
 * CustomEvent on window with the chosen file metadata in event.detail.
 */

const IMAGE_MIME_TYPES = [
  'image/png',
  'image/jpeg',
  'image/tiff',
  'image/webp',
  'image/gif',
  'image/bmp',
].join(',');

let pickerApiLoaded = false;

/**
 * @param {string} oauthToken   - User's Google OAuth access token (stored by allauth).
 * @param {string} developerKey - Browser API key with Google Picker API enabled.
 */
function openGooglePicker(oauthToken, developerKey) {
  if (!oauthToken) {
    console.error('No OAuth token available for Google Picker.');
    alert('Google Drive access is unavailable. Please sign out and sign back in to grant Drive access.');
    return;
  }

  function buildPicker() {
    // Navigable "My Drive" folder browser — filters content to images only,
    // but keeps folders visible so the user can drill into subdirectories.
    const myDriveView = new google.picker.DocsView()
      .setIncludeFolders(true)        // show folders so the user can navigate
      .setSelectFolderEnabled(false)  // prevent selecting a folder as the result
      .setMimeTypes(IMAGE_MIME_TYPES)
      .setLabel('My Drive');

    // "Shared with me" view — same folder-navigable experience
    const sharedView = new google.picker.DocsView()
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false)
      .setMimeTypes(IMAGE_MIME_TYPES)
      .setEnableDrives(true)          // include shared drives
      .setLabel('Shared with me');

    // "Recent" images — quick access to recently opened Drive images
    const recentView = new google.picker.DocsView(google.picker.ViewId.RECENTLY_PICKED)
      .setMimeTypes(IMAGE_MIME_TYPES)
      .setLabel('Recent');

    const picker = new google.picker.PickerBuilder()
      .addView(myDriveView)
      .addView(sharedView)
      .addView(recentView)
      .setOAuthToken(oauthToken)
      .setDeveloperKey(developerKey)
      .enableFeature(google.picker.Feature.MULTISELECT_ENABLED)
      .enableFeature(google.picker.Feature.SUPPORT_DRIVES) // support shared drives
      .setCallback(pickerCallback)
      .setTitle('Select images from Google Drive')
      .build();

    picker.setVisible(true);
  }

  if (pickerApiLoaded) {
    buildPicker();
  } else {
    gapi.load('picker', function () {
      pickerApiLoaded = true;
      buildPicker();
    });
  }
}

function pickerCallback(data) {
  if (data.action === google.picker.Action.PICKED) {
    const files = data.docs.map(doc => ({
      id:            doc.id,
      name:          doc.name,
      mimeType:      doc.mimeType,
      thumbnailLink: doc.thumbnails ? doc.thumbnails[doc.thumbnails.length - 1].url : '',
    }));

    window.dispatchEvent(new CustomEvent('driveFilesSelected', { detail: files }));
  }
}
