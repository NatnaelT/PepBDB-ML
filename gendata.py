import pandas as pd
import numpy as np
import argparse
from aaindex import *
from helpers import *
from paths import *
import os
import pickle

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate data for peptide-protein complexes.")
    parser.add_argument("--images", type=bool, default=False, help="Set to True to generate images. Default is False.")
    parser.add_argument("--binding_path", type=str, help="Path to save binding images.")
    parser.add_argument("--nonbinding_path", type=str, help="Path to save non-binding images.")
    args = parser.parse_args()

    # Validate that paths are provided if images is True
    if args.images:
        if not args.binding_path or not args.nonbinding_path:
            parser.error("--binding_path and --nonbinding_path are required when --images is set to True.")

    ## Load data and add headers
    peptide_list = pd.read_csv(peptide_list_txt, sep='\s+', header=None)

    headers = ['PDB ID', 'Peptide Chain ID', 'Peptide Length', 'Number of Atoms in Peptide',
               'Protein Chain ID', 'Number of Atoms in Protein',
               'Number of Atom Contacts', 'unknown1', 'unknown2', 'Resolution', 'Molecular Type']

    peptide_list.columns = headers

    peptide_list['Peptide Path'] = pepbdb + peptide_list['PDB ID'] + '_' + peptide_list['Peptide Chain ID'] + '/peptide.pdb'
    peptide_list['Protein Path'] = pepbdb + peptide_list['PDB ID'] + '_' + peptide_list['Peptide Chain ID'] + '/receptor.pdb'

    peptide_list.reset_index(drop=True)
    print(peptide_list.shape)

    #####################################################
    ## The following section is for local testing only ##
    #####################################################

    # Get the list of all directories in the given directory
    def get_dirs(directory):
        dirs = [d for d in os.listdir(directory) if os.path.isdir(os.path.join(directory, d))]
        dirs = [d[:4] for d in dirs]
        return set(dirs)

    dirs = get_dirs(pepbdb)

    # Filter peptide_list to keep only rows where the PDB ID is in the list of first 4 characters
    peptide_list = peptide_list[peptide_list['PDB ID'].isin(dirs)]

    print('\033[1mFiltering based on directory names done.\033[0m')

    #####################################################
    ## Local based filtering step is completed.        ##
    #####################################################

    print('Initial filtering...')

    ## Filter out nucleic acids, low-resolution, and small peptides
    peptide_list = peptide_list[peptide_list['Molecular Type'] != 'prot-nuc']
    peptide_list = peptide_list[peptide_list['Resolution'] < 2.5]
    peptide_list = peptide_list[peptide_list['Peptide Length'] >= 10]

    print('\033[1mInitial filtering done.\033[0m')
    print('Extracting sequences...')

    ## Extract sequences from PDB files
    peptide_list['Peptide Sequence'] = peptide_list['Peptide Path'].apply(extract_sequence)
    peptide_list['Protein Sequence'] = peptide_list['Protein Path'].apply(extract_sequence)

    print('\033[1mSequences extracted.\033[0m')

    print(f'Size of array with non-standard amino acids: {peptide_list.shape}')
    peptide_list = peptide_list[~peptide_list['Peptide Sequence'].str.contains('[UOBZJX\\*]', regex=True)]
    peptide_list = peptide_list[~peptide_list['Protein Sequence'].str.contains('[UOBZJX\\*]', regex=True)]

    print(f'Size of array after removing: {peptide_list.shape}')

    peptide_list = peptide_list.drop_duplicates(subset=['Peptide Sequence', 'Protein Sequence'])

    print('Running PRODIGY to determine binding contacts...')

    ## Determine binding residues from peptide-protein complexes
    peptide_list['Peptide Binding Indices'] = np.nan
    peptide_list['Protein Binding Indices'] = np.nan

    for index, row in peptide_list.iterrows():
        peptide_path = row['Peptide Path']
        protein_path = row['Protein Path']

        peptide_binding_positions, protein_binding_positions = label_residues(peptide_path, protein_path)

        peptide_list.at[index, 'Peptide Binding Indices'] = str(peptide_binding_positions)
        peptide_list.at[index, 'Protein Binding Indices'] = str(protein_binding_positions)

    print('\033[1mBinding indices identified.\033[0m')
    print('Adding residue-level data from AAindex1...')

    ## Add rich data from AAindex1
    features = {
        'Hydrophobicity': hydrophobicity,
        'Steric Parameter': steric_parameter,
        'Volume': residue_volume,
        'Polarizability': polarizability,
        'Helix Probability': average_relative_probability_of_helix,
        'Beta Probability': average_relative_probability_of_beta_sheet,
        'Isoelectric Point': isoelectric_point
    }

    for feature_name, feature_function in features.items():
        peptide_list[f'Peptide {feature_name}'] = peptide_list['Peptide Sequence'].apply(lambda x: feature_vector(x, feature_function))
        peptide_list[f'Protein {feature_name}'] = peptide_list['Protein Sequence'].apply(lambda x: feature_vector(x, feature_function))

    print('\033[1mAAindex features added.\033[0m')
    print('Adding HSE, ASA, and DSSP codes...')

    ## Add HSE, ASA, DSSP codes, etc.
    peptide_list[['Peptide HSE Up', 'Peptide HSE Down', 'Peptide Pseudo Angles', 'Peptide SS', 'Peptide ASA', 'Peptide Phi', 'Peptide Psi']] = peptide_list['Peptide Path'].apply(lambda x: pd.Series(safe_hse_and_dssp(x)))
    peptide_list[['Protein HSE Up', 'Protein HSE Down', 'Protein Pseudo Angles', 'Protein SS', 'Protein ASA', 'Protein Phi', 'Protein Psi']] = peptide_list['Protein Path'].apply(lambda x: pd.Series(safe_hse_and_dssp(x)))

    ## One-hot encode SS codes
    ss_columns = peptide_list.apply(one_hot_encode_row, axis=1)
    peptide_list = pd.concat([peptide_list, ss_columns], axis=1)

    print('\033[1mHSE, ASA, and DSSP codes added and encoded.\033[0m')

    ## Extend HSE and Pseudo Angles to match peptides length. Achieved by duplicating terminal values.
    peptide_list['Protein HSE Up'] = peptide_list['Protein HSE Up'].apply(extend_hse)
    peptide_list['Protein HSE Down'] = peptide_list['Protein HSE Down'].apply(extend_hse)
    peptide_list['Protein Pseudo Angles'] = peptide_list['Protein Pseudo Angles'].apply(extend_hse)

    peptide_list['Peptide HSE Up'] = peptide_list['Peptide HSE Up'].apply(extend_hse)
    peptide_list['Peptide HSE Down'] = peptide_list['Peptide HSE Down'].apply(extend_hse)
    peptide_list['Peptide Pseudo Angles'] = peptide_list['Peptide Pseudo Angles'].apply(extend_hse)

    print('\033[1mHSE data extended.\033[0m')
    print('Now generating and filtering PSSMs...')

    ## Add PSSM profiles into dataframe
    peptide_list['Peptide PSSM'] = peptide_list['Peptide Sequence'].apply(get_pssm_profile)
    peptide_list['Protein PSSM'] = peptide_list['Protein Sequence'].apply(get_pssm_profile)

    print('\033[1mPSSMs generated.\033[0m')

    ## Reduce to one peptide/protein per row
    peptide_cols = [col for col in peptide_list.columns if 'Peptide' in col] # Columns we want to keep in pep_data
    peptide_cols.remove('Peptide Length')
    protein_cols = [col for col in peptide_list.columns if 'Protein' in col] # Columns we want to keep in pro_data

    pep_data = peptide_list[peptide_cols] # Select the peptide data
    pro_data = peptide_list[protein_cols] # Select the protein data

    # Combine the two dataframes
    combined_data = pd.DataFrame(np.vstack([pep_data, pro_data.values]))
    combined_data.columns = pro_data.columns

    # Replace the original peptide_list with the combined data
    peptide_list = combined_data
    print(f'\033[1mBefore removing empty PSSMs, we have array shape of {peptide_list.shape}.\033[0m')

    contains_na = peptide_list['Protein PSSM'].apply(lambda df: df.empty or df.isna().any().any())
    peptide_list = peptide_list[~contains_na]
    peptide_list.reset_index(drop=True, inplace=True)

    print(f'\033[1mRemoving empty PSSMs leads to array shape of {peptide_list.shape}.\033[0m')

    print('\033[1mData dimensions have been reduced.\033[0m')
    print('\033[1mNow tabulating...\033[0m')

    ## Create tabular dataset, 1 row per residue
    list_of_feature_arrays = []
    for i, row in peptide_list.iterrows(): 
        arr = make_tabular_dataset(row)
        list_of_feature_arrays.append(arr)
        #if not arr.isna().any().any():
        #    list_of_feature_arrays.append(arr)
        print(f'\r{i+1}/{peptide_list.shape[0]}', end='')
    
    # Save the list to a .pkl file
    with open('/home/mhilali/projects/def-bingalls/mhilali/list_of_feature_arrays.pkl', 'wb') as file:
        pickle.dump(list_of_feature_arrays, file)
    
    ## Optional step to create images:
    if args.images:
        print('\033[1m\nNow creating images...\033[0m')
        process_images(list_of_feature_arrays, binding_path=args.binding_path, nonbinding_path=args.nonbinding_path)

    print('\033[1m\nConverted.\033[0m')

    export = pd.concat(list_of_feature_arrays)
    export = export.dropna()
    export = export.reset_index(drop=True)

    export.to_csv(peppi_data_csv, index=False)

    print(f'\033[1mComplete! Find your data file at {peppi_data_csv}, with dimensions {export.shape}.\033[0m')
